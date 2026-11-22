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

	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/redis/go-redis/v9"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	usage "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/resourceusage"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/artifactstore"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/builtin"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/httpapi"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/sandboxcontrol"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/sandboxplacement"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/sandboxrunner"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/sandboxruntime"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/warmpool"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/workspace"
)

// Built-in sandbox kinds: the shared executor container or the warm pool.
const (
	BuiltinDocker     = "docker"
	BuiltinKubernetes = "kubernetes"
)

// Config is the sandbox's environment: the plane's own variables and those of
// the control plane, the runtime, the workspace store, the runner and the
// control API.
type Config struct {
	RedisURL           string
	Provider           string
	ExecutorURL        string
	AllowWeakIsolation bool
	ActivationSecret   string
	Kubeconfig         string
	Namespace          string
	Region             string
	EmbeddedRunner     bool
	TaskGCInterval     time.Duration
	Control            sandboxcontrol.Config
	Runtime            sandboxruntime.Config
	Workspace          workspace.RepositoryConfig
	Runner             sandboxrunner.Config
	Secrets            httpapi.Secrets
}

// LoadConfig reads every sandbox variable; l reports what is missing or malformed.
func LoadConfig(l *config.Loader) Config {
	provider := strings.ToLower(strings.TrimSpace(l.StringEnv("AGENTAREA_SANDBOX_PROVIDER", "")))
	return Config{
		RedisURL:           l.RequiredEnv("AGENTAREA_REDIS_URL"),
		Provider:           provider,
		ExecutorURL:        l.StringEnv("AGENTAREA_SANDBOX_EXECUTOR_URL", ""),
		AllowWeakIsolation: l.StringEnv("AGENTAREA_SANDBOX_ALLOW_WEAK_ISOLATION", "") == "true",
		ActivationSecret:   l.StringEnv("AGENTAREA_SANDBOX_ACTIVATION_SECRET", ""),
		Kubeconfig:         l.StringEnv("KUBECONFIG", ""),
		Namespace:          l.StringEnv("AGENTAREA_K8S_NAMESPACE", "agentarea"),
		Region:             l.StringEnv("AGENTAREA_SANDBOX_REGION", ""),
		EmbeddedRunner:     l.BoolEnv("AGENTAREA_SANDBOX_EMBEDDED_RUNNER", false),
		TaskGCInterval:     l.DurationEnv("AGENTAREA_SANDBOX_TASK_GC_INTERVAL", 30*time.Second),
		Control:            sandboxcontrol.LoadConfig(l),
		Runtime:            sandboxruntime.LoadConfig(l, provider),
		Workspace:          workspace.LoadConfig(l),
		Runner:             sandboxrunner.LoadConfig(l),
		Secrets:            httpapi.LoadSecrets(l),
	}
}

// Builtin is the built-in sandbox the plane runs for builtinKind: builtinKind
// itself unless AGENTAREA_SANDBOX_PROVIDER names an external provider, else "".
func (c Config) Builtin(builtinKind string) string {
	switch cmpOr(c.Provider, builtinKind) {
	case "kubernetes", "docker", "agentarea":
		return builtinKind
	}
	return ""
}

// Hook attaches to the provider runtime before the workspace wraps it.
type Hook func(runtime sandboxruntime.ManagedRuntime, provider string) error

// Deps are what app builds the plane over; the plane closes none of them.
type Deps struct {
	// Redis holds execution records and provider sessions.
	Redis *redis.Client
	// S3 is the object store of task workspaces and published artifacts.
	S3 *s3.Client
	// Kubernetes is the warm pool's cluster; required when the built-in is BuiltinKubernetes.
	Kubernetes builtin.Cluster
	// Out carries every outbound request, by destination.
	Out   netguard.Clients
	Hooks []Hook
	Log   *slog.Logger
}

// Plane is one opened sandbox.
type Plane struct {
	Provider  string
	cfg       Config
	runtime   sandboxruntime.ComposedRuntime
	store     *sandboxcontrol.RedisStore
	repo      *workspace.Repository
	artifacts *artifactstore.Repository
	kube      *builtin.Kubernetes
	managed   sandboxruntime.ManagedRuntime
	log       *slog.Logger
}

// Open builds the runtime. builtinKind is the built-in sandbox this process
// would run (BuiltinDocker, BuiltinKubernetes, or "" for none); it is also the
// provider when AGENTAREA_SANDBOX_PROVIDER is unset. The warm pool, the shared
// executor and OpenSandbox are reached as internal services; E2B-compatible
// providers and the object store as vendors.
func Open(cfg Config, builtinKind string, d Deps) (*Plane, error) {
	if d.Redis == nil || d.S3 == nil || d.Out == nil || d.Log == nil {
		return nil, errors.New("sandbox plane needs Redis, the object store, the outbound clients and a logger")
	}
	store, err := sandboxcontrol.NewRedisStoreFromConfig(d.Redis, cfg.Control)
	if err != nil {
		return nil, fmt.Errorf("sandbox provider state: %w", err)
	}
	repo, err := workspace.NewRepository(cfg.Workspace, d.S3, s3.NewPresignClient(d.S3))
	if err != nil {
		return nil, fmt.Errorf("sandbox workspace repository: %w", err)
	}
	artifacts, err := artifactstore.New(artifactstore.ConfigFromWorkspace(cfg.Workspace), d.S3)
	if err != nil {
		return nil, fmt.Errorf("sandbox artifact store: %w", err)
	}
	p := &Plane{cfg: cfg, store: store, repo: repo, artifacts: artifacts, log: d.Log}
	internal, vendor := d.Out.Transport(netguard.Internal), d.Out.Transport(netguard.Vendor)
	executor := warmpool.Executor{Transport: internal, Secret: []byte(cfg.ActivationSecret)}

	var base sandboxruntime.ManagedRuntime
	switch cfg.Builtin(builtinKind) {
	case BuiltinDocker:
		base = builtin.NewDocker(cfg.ExecutorURL, cfg.AllowWeakIsolation, executor, d.Log.With("sandbox", "docker"))
	case BuiltinKubernetes:
		if p.kube, err = builtin.NewKubernetes(d.Kubernetes, cfg.Namespace, cfg.Runtime.Policy.TaskLeaseTTL, executor, d.Log.With("sandbox", "kubernetes")); err != nil {
			return nil, err
		}
		base = p.kube
	}
	limits := sandboxruntime.WorkspaceLimits{MaxFiles: cfg.Workspace.MaxFiles, MaxFileBytes: cfg.Workspace.MaxFileBytes, MaxBytes: cfg.Workspace.MaxBytes}
	provider := cmpOr(cfg.Provider, builtinKind)
	transport := vendor
	if provider == "opensandbox" {
		transport = internal
	}
	runtime, provider, err := sandboxruntime.New(base, d.Redis, provider, cfg.Runtime, limits, transport)
	if err != nil {
		return nil, fmt.Errorf("sandbox runtime: %w", err)
	}
	for _, hook := range d.Hooks {
		if err := hook(runtime, provider); err != nil {
			return nil, fmt.Errorf("sandbox runtime extension: %w", err)
		}
	}
	if p.runtime, err = sandboxruntime.NewWorkspaceRuntimeForProvider(runtime, cfg.Runtime.Workspace, repo, vendor); err != nil {
		return nil, fmt.Errorf("sandbox workspace runtime: %w", err)
	}
	p.Provider, p.managed = provider, runtime
	d.Log.Info("sandbox runtime configured", "provider", provider)
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

// Routes mounts the sandbox control API on mux. artifacts attach to the
// published-artifact store before it serves.
func (p *Plane) Routes(mux *http.ServeMux, artifacts ...func(*artifactstore.Repository) error) error {
	h, err := httpapi.New(p.runtime, p.store, p.cfg.Control, httpapi.SandboxPolicy{
		TaskIdleTTL: p.cfg.Runtime.Policy.TaskIdleTTL, MaxFileBytes: p.cfg.Workspace.MaxFileBytes,
	}, p.cfg.Secrets, p.log.With("component", "sandbox-api"))
	if err != nil {
		return fmt.Errorf("sandbox API: %w", err)
	}
	for _, attach := range artifacts {
		if err := attach(p.artifacts); err != nil {
			return fmt.Errorf("sandbox artifact store extension: %w", err)
		}
	}
	h.SetSandboxArtifactStore(p.artifacts)
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
	runner := sandboxrunner.NewWithPlacerAndWorkspaceRepository(p.cfg.Runner, p.store, placer, p.log, p.repo)
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
