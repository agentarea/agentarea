// Package connectorcomposition builds only the provider adapters selected for
// a data-plane agent. It never starts a listener, provisions a provider, or
// reaches Redis/control-plane storage.
package connectorcomposition

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"strings"
	"time"

	redis "github.com/go-redis/redis/v8"

	"github.com/agentarea/mcp-manager/internal/backends"
	managerconfig "github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/connectorruntime"
	"github.com/agentarea/mcp-manager/internal/connectorsandbox"
	"github.com/agentarea/mcp-manager/internal/dataplane"
	"github.com/agentarea/mcp-manager/internal/sandboxcontract"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime"
)

const (
	ProviderDisabled   = "disabled"
	ProviderDocker     = "docker"
	ProviderDataPlane  = "dataplane"
	ProviderKubernetes = "kubernetes"
)

// Config deliberately includes only provider-local execution settings. In
// particular it has no Redis, database, or customer control-plane credential.
type Config struct {
	DataPlaneID          string
	MCPProvider          string
	SandboxProvider      string
	KubernetesNamespace  string
	KubernetesKubeconfig string
	DockerRuntime        string
	DockerNetwork        string
	DockerNamePrefix     string
	DockerMaxContainers  int
	SandboxTaskLeaseTTL  time.Duration
	SandboxStateRedisURL string
	SandboxTaskIdleTTL   time.Duration
	SandboxSessionTTL    time.Duration
	SandboxProvisioning  time.Duration
	SandboxMaxFiles      int
	SandboxMaxFileBytes  int64
	SandboxMaxBytes      int64
}

// KubernetesAdapter is the shared Kubernetes implementation of the MCP
// backend and the managed sandbox runtime. One instance is safe to share when
// both capabilities select Kubernetes.
type KubernetesAdapter interface {
	backends.Backend
	sandboxruntime.ManagedRuntime
}

type newKubernetesAdapter func(Config) (KubernetesAdapter, error)

// Dependencies makes composition testable without a Kubernetes API server.
// Nil uses the production KubernetesBackend constructor.
type Dependencies struct {
	NewKubernetesAdapter newKubernetesAdapter
	NewDockerMCPAdapter  func(Config) (DockerMCPAdapter, error)
	NewDataPlaneMCP      func(Config) (backends.Backend, error)
	NewExternalSandbox   func(context.Context, Config) (sandboxruntime.ManagedRuntime, func() error, error)
}

type DockerMCPAdapter interface {
	backends.Backend
	InitializeMCPHost(context.Context) error
}

// Runtime exposes only successfully constructed adapters. Capabilities are
// therefore a fact of initialization, never an operator-provided boolean.
type Runtime struct {
	mcp         *connectorruntime.Service
	sandbox     *connectorsandbox.Dispatcher
	backends    []backends.Backend
	closers     []func() error
	reportError func(error)
}

func (r *Runtime) MCP() *connectorruntime.Service { return r.mcp }

func (r *Runtime) Sandbox() *connectorsandbox.Dispatcher { return r.sandbox }

func (r *Runtime) SetErrorReporter(reporter func(error)) { r.reportError = reporter }

func (r *Runtime) Capabilities() (mcp, sandbox bool) {
	return r != nil && r.mcp != nil, r != nil && r.sandbox != nil
}

// Close releases provider clients during process drain. KubernetesBackend's
// shutdown does not delete workloads, so this cannot uninstall a provider.
func (r *Runtime) Close(ctx context.Context) error {
	if r == nil {
		return nil
	}
	var result error
	for index := len(r.backends) - 1; index >= 0; index-- {
		result = errors.Join(result, r.backends[index].Shutdown(ctx))
	}
	for index := len(r.closers) - 1; index >= 0; index-- {
		result = errors.Join(result, r.closers[index]())
	}
	return result
}

func New(ctx context.Context, cfg Config, deps Dependencies) (*Runtime, error) {
	cfg, err := normalize(cfg)
	if err != nil {
		return nil, err
	}
	runtime := &Runtime{}
	if cfg.MCPProvider == ProviderDisabled && cfg.SandboxProvider == ProviderDisabled {
		return runtime, nil
	}
	var kubernetesAdapter KubernetesAdapter
	if cfg.MCPProvider == ProviderKubernetes || cfg.SandboxProvider == ProviderKubernetes {
		newAdapter := deps.NewKubernetesAdapter
		if newAdapter == nil {
			newAdapter = newProductionKubernetesAdapter
		}
		kubernetesAdapter, err = newAdapter(cfg)
		if err != nil {
			return nil, fmt.Errorf("initialize Kubernetes provider adapter: %w", err)
		}
		runtime.backends = append(runtime.backends, kubernetesAdapter)
	}

	switch cfg.MCPProvider {
	case ProviderDisabled:
	case ProviderKubernetes:
		runtime.mcp, err = connectorruntime.New(kubernetesAdapter, connectorruntime.Config{DataPlaneID: cfg.DataPlaneID})
	case ProviderDataPlane:
		newAdapter := deps.NewDataPlaneMCP
		if newAdapter == nil {
			newAdapter = newProductionDataPlaneMCP
		}
		var adapter backends.Backend
		adapter, err = newAdapter(cfg)
		if err == nil {
			err = adapter.Initialize(ctx)
		}
		if err == nil {
			runtime.backends = append(runtime.backends, adapter)
			runtimeConfig := connectorruntime.Config{DataPlaneID: cfg.DataPlaneID}
			if remote, ok := adapter.(interface {
				MCPHTTPClient() connectorruntime.HTTPDoer
			}); ok {
				runtimeConfig.HTTPClient = remote.MCPHTTPClient()
			}
			runtime.mcp, err = connectorruntime.New(adapter, runtimeConfig)
		}
	case ProviderDocker:
		newAdapter := deps.NewDockerMCPAdapter
		if newAdapter == nil {
			newAdapter = newProductionDockerMCPAdapter
		}
		var adapter DockerMCPAdapter
		adapter, err = newAdapter(cfg)
		if err == nil {
			err = adapter.InitializeMCPHost(ctx)
		}
		if err == nil {
			runtime.backends = append(runtime.backends, adapter)
			runtime.mcp, err = connectorruntime.New(adapter, connectorruntime.Config{DataPlaneID: cfg.DataPlaneID})
		}
	}
	if err != nil {
		_ = runtime.Close(context.Background())
		return nil, fmt.Errorf("initialize MCP provider %q: %w", cfg.MCPProvider, err)
	}

	switch cfg.SandboxProvider {
	case ProviderDisabled:
	case ProviderKubernetes:
		runtime.sandbox, err = connectorsandbox.New(kubernetesAdapter, connectorsandbox.Config{})
	default:
		newExternal := deps.NewExternalSandbox
		if newExternal == nil {
			newExternal = newProductionExternalSandbox
		}
		var managed sandboxruntime.ManagedRuntime
		var closeState func() error
		managed, closeState, err = newExternal(ctx, cfg)
		if err == nil {
			runtime.sandbox, err = connectorsandbox.New(&agentManagedRuntime{ManagedRuntime: managed}, connectorsandbox.Config{})
		}
		if err == nil && closeState != nil {
			runtime.closers = append(runtime.closers, closeState)
		}
	}
	if err != nil {
		_ = runtime.Close(context.Background())
		return nil, fmt.Errorf("initialize sandbox provider %q: %w", cfg.SandboxProvider, err)
	}
	return runtime, nil
}

// agentManagedRuntime exposes the provider-neutral file methods already
// guaranteed by ManagedRuntime as the complete on-demand file use cases the
// connector dispatcher requires. The agent has no separate durable workspace
// decorator: the external provider manager owns task binding, fencing, quota,
// and atomic upload itself.
type agentManagedRuntime struct{ sandboxruntime.ManagedRuntime }

func (r *agentManagedRuntime) PutWorkspaceFile(ctx context.Context, request sandboxcontract.FilePutRequest) (*sandboxcontract.FilePutResponse, error) {
	return r.SandboxFilePut(ctx, request)
}

func (r *agentManagedRuntime) UploadWorkspaceFile(ctx context.Context, request sandboxruntime.FileUpload, content io.Reader) (*sandboxruntime.FileWriteResult, error) {
	return r.SandboxFileUpload(ctx, request, content)
}

func (r *agentManagedRuntime) GetWorkspaceFile(ctx context.Context, request sandboxruntime.WorkspaceFileRead) (*sandboxcontract.FileGetResponse, error) {
	return r.SandboxFileGet(ctx, request.WorkspaceID, request.TaskID, request.Path)
}

func (r *agentManagedRuntime) OpenWorkspaceFile(ctx context.Context, request sandboxruntime.WorkspaceFileRead) (*sandboxruntime.FileDownload, error) {
	return r.SandboxFileDownload(ctx, request.WorkspaceID, request.TaskID, request.Path)
}

func (r *agentManagedRuntime) ListWorkspaceFiles(ctx context.Context, request sandboxruntime.WorkspaceFileList) (*sandboxcontract.FileListResponse, error) {
	return r.SandboxFileList(ctx, request.WorkspaceID, request.TaskID, request.Prefix)
}

var _ sandboxruntime.WorkspaceFileWriter = (*agentManagedRuntime)(nil)
var _ sandboxruntime.WorkspaceFileReader = (*agentManagedRuntime)(nil)

func normalize(cfg Config) (Config, error) {
	cfg.MCPProvider = strings.ToLower(strings.TrimSpace(cfg.MCPProvider))
	cfg.SandboxProvider = strings.ToLower(strings.TrimSpace(cfg.SandboxProvider))
	if cfg.MCPProvider == "" {
		cfg.MCPProvider = ProviderDisabled
	}
	if cfg.SandboxProvider == "" {
		cfg.SandboxProvider = ProviderDisabled
	}
	if strings.TrimSpace(cfg.DataPlaneID) == "" {
		return Config{}, errors.New("data_plane_id is required for runtime composition")
	}
	if !supportedMCP(cfg.MCPProvider) {
		return Config{}, fmt.Errorf("unsupported MCP provider %q", cfg.MCPProvider)
	}
	if !supportedSandbox(cfg.SandboxProvider) {
		return Config{}, fmt.Errorf("unsupported sandbox provider %q", cfg.SandboxProvider)
	}
	if (cfg.MCPProvider == ProviderKubernetes || cfg.SandboxProvider == ProviderKubernetes) && strings.TrimSpace(cfg.KubernetesNamespace) == "" {
		return Config{}, errors.New("kubernetes namespace is required for a Kubernetes provider")
	}
	if cfg.SandboxTaskLeaseTTL <= 0 {
		return Config{}, errors.New("sandbox task lease TTL must be positive")
	}
	if cfg.SandboxTaskIdleTTL == 0 {
		cfg.SandboxTaskIdleTTL = 15 * time.Minute
	}
	if cfg.SandboxProvisioning == 0 {
		cfg.SandboxProvisioning = 2 * time.Minute
	}
	if cfg.SandboxSessionTTL == 0 {
		cfg.SandboxSessionTTL = 24 * time.Hour
	}
	if cfg.SandboxMaxFiles == 0 {
		cfg.SandboxMaxFiles = 10_000
	}
	if cfg.SandboxMaxFileBytes == 0 {
		cfg.SandboxMaxFileBytes = 256 << 20
	}
	if cfg.SandboxMaxBytes == 0 {
		cfg.SandboxMaxBytes = 2 << 30
	}
	if isExternalSandbox(cfg.SandboxProvider) && strings.TrimSpace(cfg.SandboxStateRedisURL) == "" {
		return Config{}, errors.New("sandbox_state_redis_url is required for an external sandbox provider")
	}
	return cfg, nil
}

func newProductionExternalSandbox(ctx context.Context, cfg Config) (sandboxruntime.ManagedRuntime, func() error, error) {
	options, err := redis.ParseURL(cfg.SandboxStateRedisURL)
	if err != nil {
		return nil, nil, fmt.Errorf("parse agent-local sandbox state URL: %w", err)
	}
	client := redis.NewClient(options)
	closeState := client.Close
	if err := client.Ping(ctx).Err(); err != nil {
		_ = closeState()
		return nil, nil, fmt.Errorf("connect agent-local sandbox state: %w", err)
	}
	policy := sandboxruntime.ControlPolicy{
		TaskLeaseTTL: cfg.SandboxTaskLeaseTTL, TaskIdleTTL: cfg.SandboxTaskIdleTTL,
		ProviderProvisioningTimeout: cfg.SandboxProvisioning, SessionRecordTTL: cfg.SandboxSessionTTL,
	}
	limits := sandboxruntime.WorkspaceLimits{MaxFiles: cfg.SandboxMaxFiles, MaxFileBytes: cfg.SandboxMaxFileBytes, MaxBytes: cfg.SandboxMaxBytes}
	managed, selected, err := sandboxruntime.NewFromEnv(ctx, nil, client, cfg.SandboxProvider, policy, limits)
	if err != nil {
		_ = closeState()
		return nil, nil, err
	}
	if selected != cfg.SandboxProvider {
		_ = closeState()
		return nil, nil, fmt.Errorf("sandbox provider selection drifted to %q", selected)
	}
	return managed, closeState, nil
}

func supportedMCP(provider string) bool {
	return provider == ProviderDisabled || provider == ProviderDocker || provider == ProviderDataPlane || provider == ProviderKubernetes
}

func newProductionDataPlaneMCP(agentConfig Config) (backends.Backend, error) {
	cfg, err := dataplane.ClientConfigFromEnv()
	if err != nil {
		return nil, err
	}
	return &legacyDataPlaneAdapter{
		Backend: dataplane.NewClient(cfg), dataPlaneID: agentConfig.DataPlaneID,
		proxyBaseURL: strings.TrimRight(cfg.BaseURL, "/"), token: cfg.Token,
	}, nil
}

// legacyDataPlaneAdapter composes the old authenticated HTTP data plane under
// the new outbound logical plane. The legacy server independently fences every
// operation by its own owner label and rewrites that label to its host ID. Once
// that server has returned an owned status, translate only the connector-facing
// proof to the logical plane ID so connectorruntime can apply its generation
// fence without weakening the host's enforcement.
type legacyDataPlaneAdapter struct {
	backends.Backend
	dataPlaneID  string
	proxyBaseURL string
	token        string
}

func (a *legacyDataPlaneAdapter) GetInstanceStatus(ctx context.Context, instanceID string) (*backends.InstanceStatus, error) {
	status, err := a.Backend.GetInstanceStatus(ctx, instanceID)
	if err != nil {
		return nil, err
	}
	return a.translate(status, instanceID), nil
}

func (a *legacyDataPlaneAdapter) ListInstances(ctx context.Context) ([]*backends.InstanceStatus, error) {
	statuses, err := a.Backend.ListInstances(ctx)
	if err != nil {
		return nil, err
	}
	for index, status := range statuses {
		routeID := status.ServiceName
		if routeID == "" {
			routeID = status.Name
		}
		statuses[index] = a.translate(status, routeID)
	}
	return statuses, nil
}

func (a *legacyDataPlaneAdapter) translate(status *backends.InstanceStatus, routeID string) *backends.InstanceStatus {
	if status == nil {
		return nil
	}
	copy := *status
	copy.Labels = make(map[string]string, len(status.Labels)+1)
	for name, value := range status.Labels {
		copy.Labels[name] = value
	}
	copy.Labels[connectorruntime.DataPlaneIDLabel] = a.dataPlaneID
	if a.proxyBaseURL != "" {
		copy.InternalURL = a.proxyBaseURL + "/dataplane/v1/instances/" + url.PathEscape(routeID) + "/proxy"
	}
	return &copy
}

func (a *legacyDataPlaneAdapter) MCPHTTPClient() connectorruntime.HTTPDoer {
	return &legacyDataPlaneHTTPClient{token: a.token, client: &http.Client{}}
}

type legacyDataPlaneHTTPClient struct {
	token  string
	client *http.Client
}

func (c *legacyDataPlaneHTTPClient) Do(request *http.Request) (*http.Response, error) {
	request.Header.Set("Authorization", "Bearer "+c.token)
	return c.client.Do(request)
}

func newProductionDockerMCPAdapter(cfg Config) (DockerMCPAdapter, error) {
	manager := &managerconfig.Config{Container: managerconfig.ContainerConfig{
		Runtime: cfg.DockerRuntime, Network: cfg.DockerNetwork, NamePrefix: cfg.DockerNamePrefix, MaxContainers: cfg.DockerMaxContainers,
		StartupTimeout: 2 * time.Minute, ShutdownTimeout: 30 * time.Second, DefaultIsolationTier: managerconfig.IsolationStandard,
	}}
	return backends.NewDockerBackend(manager, slog.New(slog.NewTextHandler(ioDiscard{}, nil))), nil
}

func supportedSandbox(provider string) bool {
	switch provider {
	case ProviderDisabled, ProviderKubernetes, "opensandbox", "e2b", "cube":
		return true
	default:
		return false
	}
}

func isExternalSandbox(provider string) bool {
	return provider == "opensandbox" || provider == "e2b" || provider == "cube"
}

func newProductionKubernetesAdapter(cfg Config) (KubernetesAdapter, error) {
	kubernetes := managerconfig.DefaultKubernetesConfig()
	kubernetes.Enabled = true
	kubernetes.Namespace = cfg.KubernetesNamespace
	kubernetes.Kubeconfig = cfg.KubernetesKubeconfig
	// NewKubernetesBackend does not use Redis. Keep the agent's local config
	// minimal rather than loading manager configuration and inherited control
	// plane credentials.
	manager := &managerconfig.Config{
		Container: managerconfig.ContainerConfig{
			MaxContainers:        50,
			StartupTimeout:       2 * time.Minute,
			ShutdownTimeout:      30 * time.Second,
			DefaultIsolationTier: managerconfig.IsolationUntrusted,
		},
		Kubernetes: kubernetes,
	}
	logger := slog.New(slog.NewTextHandler(ioDiscard{}, nil))
	return backends.NewKubernetesBackend(manager, logger, cfg.SandboxTaskLeaseTTL)
}

// ioDiscard is a local Writer so this package does not set global logging.
type ioDiscard struct{}

func (ioDiscard) Write(p []byte) (int, error) { return len(p), nil }
