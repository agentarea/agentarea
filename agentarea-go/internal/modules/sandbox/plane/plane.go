// Package plane assembles the sandbox: the provider runtime under the task
// workspace, the control API the platform calls, the execution consumer and
// the warm-pool task GC. The mcp role serves the API; the sandbox role runs
// the consumer.
package plane

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	usage "github.com/agentarea/agentarea/agentarea-go/internal/kernel/resourceusage"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/backends/artifactstore"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/backends/builtin"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/backends/httpapi"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/backends/sandboxcontrol"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/backends/sandboxplacement"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/backends/sandboxrunner"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/backends/sandboxruntime"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/backends/workspace"
)

// Built-in sandbox kinds: the shared executor container or the warm pool.
const (
	BuiltinDocker     = "docker"
	BuiltinKubernetes = "kubernetes"
)

// Config is the sandbox's own environment; the provider, policy and workspace
// packages read theirs (AGENTAREA_SANDBOX_*) when the plane is opened.
type Config struct {
	RedisURL       string
	Provider       string
	ExecutorURL    string
	Kubeconfig     string
	Namespace      string
	Region         string
	EmbeddedRunner bool
	TaskGCInterval time.Duration
}

// LoadConfig reads the plane's variables; l reports what is malformed.
func LoadConfig(l *config.Loader) Config {
	return Config{
		RedisURL:       l.RequiredEnv("AGENTAREA_REDIS_URL"),
		Provider:       strings.ToLower(strings.TrimSpace(l.StringEnv("AGENTAREA_SANDBOX_PROVIDER", ""))),
		ExecutorURL:    l.StringEnv("AGENTAREA_SANDBOX_EXECUTOR_URL", ""),
		Kubeconfig:     l.StringEnv("KUBECONFIG", ""),
		Namespace:      l.StringEnv("AGENTAREA_K8S_NAMESPACE", "agentarea"),
		Region:         l.StringEnv("AGENTAREA_SANDBOX_REGION", ""),
		EmbeddedRunner: l.BoolEnv("AGENTAREA_SANDBOX_EMBEDDED_RUNNER", false),
		TaskGCInterval: l.DurationEnv("AGENTAREA_SANDBOX_TASK_GC_INTERVAL", 30*time.Second),
	}
}

// Hook attaches to the provider runtime before the workspace wraps it.
type Hook func(runtime sandboxruntime.ManagedRuntime, provider string) error

// Plane is one opened sandbox.
type Plane struct {
	Provider  string
	cfg       Config
	runtime   sandboxruntime.ComposedRuntime
	store     *sandboxcontrol.RedisStore
	control   sandboxcontrol.Config
	policy    sandboxruntime.ControlPolicy
	workspace workspace.RepositoryConfig
	kube      *builtin.Kubernetes
	managed   sandboxruntime.ManagedRuntime
	log       *slog.Logger
}

// Open builds the runtime. builtinKind is the built-in sandbox this process
// would run (BuiltinDocker, BuiltinKubernetes, or "" for none); it is also the
// provider when AGENTAREA_SANDBOX_PROVIDER is unset.
func Open(ctx context.Context, cfg Config, builtinKind string, hooks []Hook, log *slog.Logger) (_ *Plane, err error) {
	policy, err := sandboxruntime.LoadControlPolicyFromEnv()
	if err != nil {
		return nil, fmt.Errorf("sandbox control policy: %w", err)
	}
	ws, err := workspace.LoadConfigFromEnv()
	if err != nil {
		return nil, fmt.Errorf("sandbox workspace policy: %w", err)
	}
	control, err := sandboxcontrol.LoadConfigFromEnv(cfg.RedisURL)
	if err != nil {
		return nil, fmt.Errorf("sandbox control plane: %w", err)
	}
	store, err := sandboxcontrol.NewRedisStoreFromConfig(control)
	if err != nil {
		return nil, fmt.Errorf("sandbox provider state: %w", err)
	}
	defer func() {
		if err != nil {
			_ = store.Close()
		}
	}()
	p := &Plane{cfg: cfg, store: store, control: control, policy: policy, workspace: ws, log: log}

	var base sandboxruntime.ManagedRuntime
	switch provider := cmpOr(cfg.Provider, builtinKind); provider {
	case "kubernetes", "docker", "agentarea":
		switch builtinKind {
		case BuiltinDocker:
			base = builtin.NewDocker(cfg.ExecutorURL, log.With("sandbox", "docker"))
		case BuiltinKubernetes:
			cs, err := builtin.Clientset(cfg.Kubeconfig, log)
			if err != nil {
				return nil, err
			}
			if p.kube, err = builtin.NewKubernetes(cs, cfg.Namespace, policy.TaskLeaseTTL, log.With("sandbox", "kubernetes")); err != nil {
				return nil, err
			}
			base = p.kube
		}
	}
	limits := sandboxruntime.WorkspaceLimits{MaxFiles: ws.MaxFiles, MaxFileBytes: ws.MaxFileBytes, MaxBytes: ws.MaxBytes}
	runtime, provider, err := sandboxruntime.NewFromEnv(ctx, base, store.RedisClient(), builtinKind, policy, limits)
	if err != nil {
		return nil, fmt.Errorf("sandbox runtime: %w", err)
	}
	for _, hook := range hooks {
		if err := hook(runtime, provider); err != nil {
			return nil, fmt.Errorf("sandbox runtime extension: %w", err)
		}
	}
	wp, err := sandboxruntime.LoadWorkspaceProviderFromEnv()
	if err != nil {
		return nil, fmt.Errorf("sandbox workspace provider: %w", err)
	}
	if p.runtime, err = sandboxruntime.NewWorkspaceRuntimeForProvider(ctx, runtime, wp, ws); err != nil {
		return nil, fmt.Errorf("sandbox workspace runtime: %w", err)
	}
	p.Provider, p.managed = provider, runtime
	log.Info("sandbox runtime configured", "provider", provider)
	return p, nil
}

func cmpOr(a, b string) string {
	if a != "" {
		return a
	}
	return b
}

// Allocations samples an external provider's live inventory; nil for a
// built-in sandbox or a provider runtime that lists no allocations.
func (p *Plane) Allocations() usage.Sampler {
	switch p.Provider {
	case "kubernetes", "docker", "agentarea":
		return nil
	}
	inventory, ok := p.managed.(sandboxruntime.AllocationInventory)
	if !ok {
		return nil
	}
	return sandboxruntime.NewAllocationSampler(inventory, p.Provider)
}

// Redis is the client of the provider state store.
func (p *Plane) Redis() *redis.Client { return p.store.RedisClient() }

// Close releases the provider state store.
func (p *Plane) Close() error { return p.store.Close() }

// Routes mounts the sandbox control API on mux. artifacts attach to the
// published-artifact store before it serves.
func (p *Plane) Routes(ctx context.Context, mux *http.ServeMux, artifacts ...func(*artifactstore.Repository) error) error {
	h, err := httpapi.New(p.runtime, p.control, httpapi.SandboxPolicy{
		TaskIdleTTL: p.policy.TaskIdleTTL, MaxFileBytes: p.workspace.MaxFileBytes,
	}, p.log.With("component", "sandbox-api"))
	if err != nil {
		return fmt.Errorf("sandbox API: %w", err)
	}
	repo, err := artifactstore.NewFromConfig(ctx, artifactstore.ConfigFromWorkspace(p.workspace))
	if err != nil {
		return fmt.Errorf("sandbox artifact store: %w", err)
	}
	for _, attach := range artifacts {
		if err := attach(repo); err != nil {
			return fmt.Errorf("sandbox artifact store extension: %w", err)
		}
	}
	h.SetSandboxArtifactStore(repo)
	h.Routes(mux)
	return nil
}

// EmbeddedRunner reports whether the mcp role also consumes executions
// (AGENTAREA_SANDBOX_EMBEDDED_RUNNER, the compose setup).
func (p *Plane) EmbeddedRunner() bool { return p.cfg.EmbeddedRunner }

// Run consumes sandbox executions until ctx ends.
func (p *Plane) Run(ctx context.Context) error {
	placer, err := sandboxplacement.NewRegistry(sandboxplacement.Target{
		Executor:     p.runtime,
		Capabilities: sandboxplacement.Capabilities{Name: p.Provider, Region: p.cfg.Region},
	})
	if err != nil {
		return fmt.Errorf("sandbox placement: %w", err)
	}
	repo, err := workspace.NewRepositoryFromConfig(ctx, p.workspace)
	if err != nil {
		return fmt.Errorf("sandbox output repository: %w", err)
	}
	runner := sandboxrunner.NewWithPlacerAndWorkspaceRepository(sandboxrunner.ConfigFromEnv(), p.store, placer, p.log, repo)
	if err := runner.Run(ctx); err != nil && !errors.Is(err, context.Canceled) {
		return fmt.Errorf("sandbox runner: %w", err)
	}
	return nil
}

// GC deletes expired warm-pool task pods every interval until ctx ends; it
// has nothing to do without the Kubernetes built-in sandbox.
func (p *Plane) GC(ctx context.Context) error {
	if p.kube == nil || p.cfg.TaskGCInterval <= 0 {
		<-ctx.Done()
		return nil
	}
	client := p.kube.GetWarmPoolClient()
	ticker := time.NewTicker(p.cfg.TaskGCInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return nil
		case now := <-ticker.C:
			deleted, err := client.DeleteExpiredTaskPods(ctx, now.UTC())
			if err != nil {
				p.log.Warn("sandbox task GC failed", "error", err)
				continue
			}
			if deleted > 0 {
				p.log.Info("sandbox task GC deleted expired pods", "deleted", deleted)
			}
		}
	}
}
