package mcpgateway

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/agentarea/mcp-manager/internal/providers"
)

// ProviderSelector resolves the data plane that owns one instance. The demand
// runtime depends on this capability rather than on the concrete provider
// registry, so lifecycle behaviour can be exercised without a live data plane.
type ProviderSelector interface {
	GetProvider(*models.MCPServerInstance) (providers.Provider, error)
}

type ProviderRuntime struct {
	providers      ProviderSelector
	backend        backends.Backend
	config         *config.Config
	imagePolicy    ImagePolicy
	startupTimeout time.Duration
}

func NewProviderRuntime(providerManager ProviderSelector, backend backends.Backend, cfg *config.Config, imagePolicy ImagePolicy, startupTimeout time.Duration) (*ProviderRuntime, error) {
	if providerManager == nil || backend == nil || cfg == nil || startupTimeout <= 0 {
		return nil, fmt.Errorf("MCP provider runtime requires providers, backend, config, and positive startup timeout")
	}
	return &ProviderRuntime{
		providers:      providerManager,
		backend:        backend,
		config:         cfg,
		imagePolicy:    imagePolicy,
		startupTimeout: startupTimeout,
	}, nil
}

func (r *ProviderRuntime) EnsureReady(ctx context.Context, instance *models.MCPServerInstance) (string, error) {
	provider, err := r.providers.GetProvider(instance)
	if err != nil {
		return "", err
	}
	instanceType, _ := instance.JSONSpec["type"].(string)
	if instanceType != "docker" && instanceType != "command" && instanceType != "kubernetes" {
		return "", fmt.Errorf("MCP demand gateway supports container-backed instances only, got %q", instanceType)
	}
	// Admission runs before the workload is inspected, not just before it is
	// created: an instance whose spec was edited to something inadmissible must
	// stop being served, not keep answering from the pod it already had.
	if err := r.authorize(instanceType, instance); err != nil {
		return "", err
	}

	status, statusErr := r.backend.GetInstanceStatus(ctx, instance.InstanceID)
	if statusErr != nil && !errors.Is(statusErr, backends.ErrInstanceNotFound) {
		return "", fmt.Errorf("inspect MCP runtime status: %w", statusErr)
	}
	if errors.Is(statusErr, backends.ErrInstanceNotFound) {
		if err := provider.CreateInstance(ctx, instance); err != nil {
			return "", err
		}
	}
	if statusErr != nil || !runtimeStatusReady(status.Status) {
		deadline := time.NewTimer(r.startupTimeout)
		defer deadline.Stop()
		ticker := time.NewTicker(500 * time.Millisecond)
		defer ticker.Stop()
		for {
			status, statusErr = r.backend.GetInstanceStatus(ctx, instance.InstanceID)
			if statusErr == nil && runtimeStatusReady(status.Status) {
				break
			}
			if statusErr != nil && !errors.Is(statusErr, backends.ErrInstanceNotFound) {
				return "", r.cleanupFailedStart(instance, fmt.Errorf("inspect MCP runtime while starting: %w", statusErr))
			}
			select {
			case <-ctx.Done():
				return "", r.cleanupFailedStart(instance, ctx.Err())
			case <-deadline.C:
				if statusErr != nil {
					return "", r.cleanupFailedStart(instance, fmt.Errorf("MCP instance did not become ready: %w", statusErr))
				}
				return "", r.cleanupFailedStart(instance, fmt.Errorf("MCP instance did not become ready; last state %q", status.Status))
			case <-ticker.C:
			}
		}
	}

	// A declared-but-unusable port is a spec error, not an invitation to guess:
	// silently falling back to 8000 would proxy the request to whatever happens
	// to be listening there. Only an absent port takes the documented default.
	port := 8000
	if instanceType == "command" {
		// command instances are wrapped by mcp-bridge, which always listens here
		// regardless of any port in the spec.
		port = 8080
	} else if rawPort, declared := instance.JSONSpec["port"]; declared && rawPort != nil {
		var parsed int
		switch value := rawPort.(type) {
		case float64:
			parsed = int(value)
			if float64(parsed) != value {
				return "", fmt.Errorf("MCP instance port %v is not an integer", value)
			}
		case int:
			parsed = value
		default:
			return "", fmt.Errorf("MCP instance port %v is not a number", rawPort)
		}
		if parsed <= 0 || parsed > 65535 {
			return "", fmt.Errorf("MCP instance port %d is outside 1-65535", parsed)
		}
		port = parsed
	}
	var base string
	if r.config.Environment == "kubernetes" {
		base = r.config.Kubernetes.GetInternalServiceURL(instance.InstanceID, port)
	} else {
		base = r.config.GetServiceURL(instance.InstanceID, port)
	}
	return strings.TrimRight(base, "/") + "/mcp", nil
}

// authorize admits the instance against the operator's declared lists. The two
// container-backed shapes name their code differently — an image reference or a
// package to fetch — so each is checked against the list that describes it.
func (r *ProviderRuntime) authorize(instanceType string, instance *models.MCPServerInstance) error {
	if instanceType == "command" {
		command, _ := instance.JSONSpec["command"].(string)
		return r.imagePolicy.AuthorizeCommand(command, commandArgs(instance.JSONSpec))
	}
	image, _ := instance.JSONSpec["image"].(string)
	return r.imagePolicy.AuthorizeImage(image)
}

// commandArgs reads the stdio arguments the same way the Kubernetes provider
// does when it builds the container command, so admission judges the invocation
// that will actually run.
func commandArgs(jsonSpec map[string]any) []string {
	raw, ok := jsonSpec["args"].([]any)
	if !ok {
		return nil
	}
	args := make([]string, 0, len(raw))
	for _, entry := range raw {
		if arg, ok := entry.(string); ok {
			args = append(args, arg)
		}
	}
	return args
}

func (r *ProviderRuntime) cleanupFailedStart(instance *models.MCPServerInstance, cause error) error {
	cleanupCtx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	provider, err := r.providers.GetProvider(instance)
	if err != nil {
		return errors.Join(cause, err)
	}
	if err := provider.DeleteInstance(cleanupCtx, instance.InstanceID, instance.Name); err != nil && !errors.Is(err, backends.ErrInstanceNotFound) {
		return errors.Join(cause, fmt.Errorf("cleanup failed MCP activation: %w", err))
	}
	return cause
}

func (r *ProviderRuntime) Delete(ctx context.Context, instance *models.MCPServerInstance) error {
	provider, err := r.providers.GetProvider(instance)
	if err != nil {
		return err
	}
	if err := provider.DeleteInstance(ctx, instance.InstanceID, instance.Name); err != nil && !errors.Is(err, backends.ErrInstanceNotFound) {
		return err
	}
	return nil
}

func runtimeStatusReady(status string) bool {
	switch strings.ToLower(status) {
	case "running", "healthy", "ready":
		return true
	default:
		return false
	}
}
