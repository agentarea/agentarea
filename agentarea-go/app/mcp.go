package app

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"strconv"
	"strings"
	"time"

	"go.opentelemetry.io/otel"

	"github.com/agentarea/agentarea/agentarea-go/ext"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	kblob "github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/lifecycle"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	knetguard "github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	kobs "github.com/agentarea/agentarea/agentarea-go/internal/kernel/obs"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/gateway"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/gateway/storage"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/runtime"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/runtime/dataplane"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/runtime/docker"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/runtime/kube"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/runtime/packages"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/runtime/workload"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster/netguard"
	clusterobs "github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster/obs"
	"github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster/secrets"
)

const (
	mcpHostMode       = "dataplane"
	mcpReadTimeout    = 30 * time.Second
	mcpWriteTimeout   = 35 * time.Minute
	mcpHeaderTimeout  = 10 * time.Second
	mcpIdleConnection = 120 * time.Second
)

// mcpConfig is the environment of the MCP runtime, wherever it runs: the mcp
// role, and serve and worker once they call it in process.
type mcpConfig struct {
	Runtime   runtime.Config
	Docker    docker.Config
	Kube      kube.Config
	Dataplane dataplane.ClientConfig
	Storage   storage.Config
	Packages  packages.Config
	Blob      kblob.Config
}

// loadMCPConfig reads the runtime and its backend's variables; l reports what is missing.
func loadMCPConfig(l *config.Loader) mcpConfig {
	c := mcpConfig{Runtime: runtime.LoadConfig(l), Storage: storage.LoadConfig(l), Packages: packages.LoadConfig(l), Blob: kblob.LoadConfig(l)}
	switch c.Runtime.Backend {
	case runtime.BackendDocker:
		c.Docker = docker.LoadConfig(l)
	case runtime.BackendKubernetes:
		c.Kube = kube.LoadConfig(l)
	case runtime.BackendDataplane:
		c.Dataplane = dataplane.LoadClientConfig(l)
	}
	return c
}

// mcpDeps is what the runtime is built over in a process that has a database.
type mcpDeps struct {
	DB       db.Database
	Secrets  *secrets.Factory
	Outbound *netguard.Outbound
	Hooks    []ext.WorkloadHooks
	Log      *slog.Logger
}

// newMCPRuntime builds the backend the configuration names and the runtime over it.
func newMCPRuntime(ctx context.Context, c mcpConfig, d mcpDeps) (*runtime.Runtime, error) {
	rd := runtime.Deps{
		Config: c.Runtime, DB: d.DB, Secrets: d.Secrets, Log: d.Log, Meter: otel.Meter(kobs.MeterScope),
		Specs:     catalog.New(catalog.Deps{DB: d.DB, Authority: authz.WorkspaceScoped{}, Log: d.Log}).MCPSpecs(),
		Storage:   storage.NewIssuer([]byte(c.Runtime.GatewaySecret), c.Storage.ManagerURL),
		Workloads: d.Outbound.Transport(knetguard.Internal),
		URLs:      d.Outbound.Transport(knetguard.Member),
	}
	switch c.Runtime.Backend {
	case runtime.BackendDocker:
		b, err := docker.New(c.Docker, d.Log.With("backend", "docker"))
		if err != nil {
			return nil, fmt.Errorf("docker backend: %w", err)
		}
		rd.Backend, rd.Validator = b, dockerValidator(b)
	case runtime.BackendKubernetes:
		b, err := kube.New(c.Kube, d.Log.With("backend", "kubernetes"))
		if err != nil {
			return nil, fmt.Errorf("kubernetes backend: %w", err)
		}
		if err := b.EnsureNamespace(ctx); err != nil {
			return nil, fmt.Errorf("kubernetes backend: %w", err)
		}
		rd.Backend = b
	case runtime.BackendDataplane:
		b, err := dataplane.NewClient(c.Dataplane, d.Outbound.Transport(knetguard.Internal))
		if err != nil {
			return nil, fmt.Errorf("data-plane backend: %w", err)
		}
		rd.Backend, rd.Remote = b, b
	default:
		return nil, fmt.Errorf("MCP backend %q is not one of docker, kubernetes, dataplane", c.Runtime.Backend)
	}
	applyWorkloadHooks(&rd, d.Hooks)
	rd.Packages = func(rt *runtime.Runtime) (runtime.Packages, error) {
		o := packages.Options{Config: c.Packages, Workloads: rt, Backend: rd.Backend,
			LocalImages: c.Runtime.Backend == runtime.BackendDocker,
			Registries:  &http.Client{Transport: d.Outbound.Transport(knetguard.Vendor)},
			Pack:        &http.Client{Transport: d.Outbound.Transport(knetguard.Internal)},
			Log:         d.Log.With("component", "mcp-packages")}
		if rd.Remote != nil {
			o.Remote = rd.Remote
		}
		return packages.New(o)
	}
	return runtime.New(rd)
}

func dockerValidator(b *docker.Backend) runtime.Validator {
	return func(ctx context.Context, spec map[string]any) (service.RuntimeValidation, error) {
		r, err := b.ValidateDryRun(ctx, spec)
		if err != nil {
			return service.RuntimeValidation{}, err
		}
		raw, err := json.Marshal(r)
		if err != nil {
			return service.RuntimeValidation{}, err
		}
		var details map[string]any
		if err := json.Unmarshal(raw, &details); err != nil {
			return service.RuntimeValidation{}, err
		}
		return service.RuntimeValidation{Valid: r.Valid, Details: details, Message: strings.Join(r.Errors, "; ")}, nil
	}
}

// runMCP is the mcp role: the MCP gateway and workload lifecycle over the
// database, or, with AGENTAREA_MCP_MODE=dataplane, a remote workload host.
func (b *Build) runMCP(ctx context.Context) error {
	l := config.New(b.lookup)
	common := config.LoadCommon(l)
	mode := l.OneOfEnv("AGENTAREA_MCP_MODE", "", mcpHostMode)
	if mode == mcpHostMode {
		return b.runMCPHost(ctx, l, common)
	}
	return b.runMCPControl(ctx, l, common)
}

func mcpListen(l *config.Loader) string {
	host := l.StringEnv("HOST", "0.0.0.0")
	port := l.IntEnv("PORT", 8000)
	if port < 0 || port > 65535 {
		l.Fail("PORT", fmt.Errorf("must be a port number, got %d", port))
	}
	return net.JoinHostPort(host, strconv.Itoa(port))
}

func (b *Build) runMCPControl(ctx context.Context, l *config.Loader, common config.Common) (err error) {
	addr := mcpListen(l)
	dbCfg := db.LoadConfig(l)
	secretsCfg := ksecrets.LoadConfig(l)
	outCfg := knetguard.LoadConfig(l)
	spend := money.LoadSpendCurrency(l)
	mc := loadMCPConfig(l)
	if err := l.Err(); err != nil {
		return fmt.Errorf("configuration: %w", err)
	}
	log := newLogger(b.stderr, common).With("component", "mcp")
	tel, err := clusterobs.Setup(ctx, clusterobs.Options{Enabled: common.OTelEnabled, Service: "agentarea-mcp",
		Version: buildVersion(), Environment: common.Env, Getenv: func(name string) string { v, _ := b.lookup(name); return v }})
	if err != nil {
		return fmt.Errorf("telemetry: %w", err)
	}
	defer func() { err = errors.Join(err, tel.Shutdown(context.WithoutCancel(ctx))) }()
	pools, err := db.Open(ctx, dbCfg, log)
	if err != nil {
		return fmt.Errorf("database: %w", err)
	}
	defer pools.Close()
	sf, err := secrets.NewFactory(secretsCfg, &http.Client{})
	if err != nil {
		return fmt.Errorf("secrets: %w", err)
	}
	trust, err := netguard.LoadTrust(outCfg.ExtraCACerts)
	if err != nil {
		return fmt.Errorf("outbound trust: %w", err)
	}
	outbound, err := netguard.New(outCfg, trust, log, netguard.Options{})
	if err != nil {
		return fmt.Errorf("outbound: %w", err)
	}
	exts, err := b.resolveExtensions(ctx, ext.Deps{Logger: log, Config: config.New(b.lookup), DB: pools}, spend)
	if err != nil {
		return err
	}
	defer func() { err = errors.Join(err, exts.Close()) }()
	rt, err := newMCPRuntime(ctx, mc, mcpDeps{DB: pools, Secrets: sf, Outbound: outbound, Hooks: exts.WorkloadHooks, Log: log})
	if err != nil {
		return err
	}
	gw, err := rt.ServedGateway()
	if err != nil {
		return err
	}
	mux := http.NewServeMux()
	gw.Routes(mux)
	if mc.Storage.ManagerURL != "" {
		store, err := storage.NewObjectStore(mc.Blob)
		if err != nil {
			return fmt.Errorf("MCP storage: %w", err)
		}
		h, err := storage.NewHandler([]byte(mc.Runtime.GatewaySecret), mc.Blob.ArtifactsBucket, store,
			storageInstances{rt: rt}, mc.Storage.Writes, log.With("component", "mcp-storage"))
		if err != nil {
			return fmt.Errorf("MCP storage: %w", err)
		}
		mux.Handle("/mcp/{instance_id}/storage/", h)
	}
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK) })
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		if err := pools.Ping(r.Context()); err != nil {
			log.Warn("mcp role not ready", "error", err)
			http.Error(w, "database unavailable", http.StatusServiceUnavailable)
			return
		}
		w.WriteHeader(http.StatusOK)
	})
	g := lifecycle.NewGroup(lifecycle.Options{StartupTimeout: common.StartupTimeout, ShutdownTimeout: common.ShutdownTimeout})
	g.Add(newHTTPComponent("mcp", addr, mux, log), &runComponent{name: "mcp-reaper", run: rt.Run, log: log})
	for i, h := range exts.WorkloadHooks {
		if h.Run != nil {
			g.Add(&runComponent{name: fmt.Sprintf("workload hooks %d", i+1), run: h.Run, close: h.Close, log: log})
		}
	}
	return g.Run(ctx)
}

func (b *Build) runMCPHost(ctx context.Context, l *config.Loader, common config.Common) (err error) {
	hc := dataplane.LoadHostConfig(l)
	rc := runtime.Config{Backend: runtime.LoadBackend(l)}
	var dc docker.Config
	var kc kube.Config
	switch rc.Backend {
	case runtime.BackendDocker:
		dc = docker.LoadConfig(l)
	case runtime.BackendKubernetes:
		kc = kube.LoadConfig(l)
	default:
		l.Fail("AGENTAREA_MCP_BACKEND", errors.New("a data-plane host runs workloads itself: docker or kubernetes"))
	}
	spend := money.LoadSpendCurrency(l)
	if err := l.Err(); err != nil {
		return fmt.Errorf("configuration: %w", err)
	}
	log := newLogger(b.stderr, common).With("component", "mcp-host")
	var backend workload.Backend
	if rc.Backend == runtime.BackendDocker {
		if backend, err = docker.New(dc, log.With("backend", "docker")); err != nil {
			return fmt.Errorf("docker backend: %w", err)
		}
	} else {
		kb, err := kube.New(kc, log.With("backend", "kubernetes"))
		if err != nil {
			return fmt.Errorf("kubernetes backend: %w", err)
		}
		if err := kb.EnsureNamespace(ctx); err != nil {
			return fmt.Errorf("kubernetes backend: %w", err)
		}
		backend = kb
	}
	extDeps := ext.Deps{Logger: log, Config: config.New(b.lookup)}
	exts, err := b.resolveExtensions(ctx, extDeps, spend)
	if err != nil {
		return err
	}
	defer func() { err = errors.Join(err, exts.Close()) }()
	handler, err := dataplane.NewHost(hc, backend, log, func(r httpx.Router) error {
		for _, h := range exts.WorkloadHooks {
			if h.HostRoutes == nil {
				continue
			}
			if err := h.HostRoutes(ctx, extDeps, r); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		return err
	}
	g := lifecycle.NewGroup(lifecycle.Options{StartupTimeout: common.StartupTimeout, ShutdownTimeout: common.ShutdownTimeout})
	g.Add(newHTTPComponent("mcp-host", hc.Addr, handler, log))
	for i, h := range exts.WorkloadHooks {
		if h.Run != nil {
			g.Add(&runComponent{name: fmt.Sprintf("workload hooks %d", i+1), run: h.Run, close: h.Close, log: log})
		}
	}
	return g.Run(ctx)
}

// storageInstances is what the storage API reads of an instance.
type storageInstances struct{ rt *runtime.Runtime }

func (s storageInstances) Instance(ctx context.Context, instanceID string) (storage.Instance, error) {
	ws, spec, err := s.rt.StorageInstance(ctx, instanceID)
	if errors.Is(err, gateway.ErrInstanceNotFound) {
		return storage.Instance{}, storage.ErrInstanceNotFound
	}
	if err != nil {
		return storage.Instance{}, err
	}
	return storage.Instance{WorkspaceID: ws, Spec: spec}, nil
}

// applyWorkloadHooks adapts every overlay's MCP attach points to the runtime's.
func applyWorkloadHooks(rd *runtime.Deps, hooks []ext.WorkloadHooks) {
	var specHooks []func(context.Context, string, string, *ext.MCPWorkload) error
	var participants []func(context.Context, ext.Querier, ext.MCPLifecycleChange) error
	for _, h := range hooks {
		if h.MCPWorkload != nil {
			specHooks = append(specHooks, h.MCPWorkload)
		}
		if h.MCPLifecycle != nil {
			participants = append(participants, h.MCPLifecycle)
		}
		if h.MCPRequests != nil {
			rd.Requests = append(rd.Requests, extRequests{o: h.MCPRequests})
		}
		if h.MCPOperations != nil {
			rd.Observers = append(rd.Observers, extOperations{o: h.MCPOperations})
		}
	}
	if len(specHooks) > 0 {
		rd.SpecHook = func(ctx context.Context, instanceID, workspaceID string, spec *workload.Spec) error {
			w := ext.MCPWorkload{Environment: spec.Environment, Labels: spec.Labels}
			for _, f := range specHooks {
				if err := f(ctx, instanceID, workspaceID, &w); err != nil {
					return err
				}
			}
			spec.Environment, spec.Labels = w.Environment, w.Labels
			return nil
		}
	}
	if len(participants) > 0 {
		rd.Participant = func(ctx context.Context, q db.Querier, c runtime.LifecycleChange) error {
			ec := ext.MCPLifecycleChange{InstanceID: c.InstanceID, WorkspaceID: c.WorkspaceID, Generation: c.Generation,
				State: c.State, Transition: string(c.Transition), Reason: c.Reason, UpdatedAt: c.UpdatedAt}
			for _, f := range participants {
				if err := f(ctx, q, ec); err != nil {
					return err
				}
			}
			return nil
		}
	}
}

type extRequests struct{ o ext.MCPRequestObserver }

func extRequest(r gateway.RequestStarted) ext.MCPRequest {
	return ext.MCPRequest{RequestID: r.RequestID, InstanceID: r.InstanceID, WorkspaceID: r.WorkspaceID,
		Method: r.Method, MCPMethod: r.MCPMethod, MCPName: r.MCPName, StartedAt: r.StartedAt}
}

func (e extRequests) Started(ctx context.Context, r gateway.RequestStarted) error {
	return e.o.Started(ctx, extRequest(r))
}

func (e extRequests) Completed(ctx context.Context, r gateway.RequestCompleted) error {
	done := ext.MCPRequestDone{MCPRequest: extRequest(r.RequestStarted), EndedAt: r.EndedAt, StatusCode: r.StatusCode,
		Canceled: r.Canceled, Answer: string(r.Answer)}
	if c := r.ColdStart; c != nil {
		done.ColdStart = &ext.MCPColdStart{Outcome: string(c.Outcome), Reason: c.Reason, Running: c.Running, Listening: c.Listening, Total: c.Total}
	}
	return e.o.Completed(ctx, done)
}

type extOperations struct{ o ext.MCPOperationObserver }

func (e extOperations) Operation(ctx context.Context, op runtime.Operation) error {
	return e.o.Operation(ctx, ext.MCPOperation{InstanceID: op.InstanceID, WorkspaceID: op.WorkspaceID,
		OperationID: op.OperationID, Kind: string(op.Kind), Phase: string(op.Phase), ObservedAt: op.ObservedAt})
}

func (e extOperations) Boundary(ctx context.Context, b runtime.BoundaryObservation) error {
	return e.o.Boundary(ctx, ext.MCPBoundary{InstanceID: b.InstanceID, WorkspaceID: b.WorkspaceID,
		OperationID: b.OperationID, Boundary: string(b.Boundary)})
}

// httpComponent serves a handler without the API edge: the MCP data path
// streams for up to 35 minutes, carries 64 MiB objects and answers no browser.
type httpComponent struct {
	name   string
	srv    *http.Server
	log    *slog.Logger
	failed chan error
}

func newHTTPComponent(name, addr string, h http.Handler, log *slog.Logger) *httpComponent {
	return &httpComponent{name: name, log: log, failed: make(chan error, 1), srv: &http.Server{
		Addr: addr, Handler: h, ReadTimeout: mcpReadTimeout, WriteTimeout: mcpWriteTimeout,
		ReadHeaderTimeout: mcpHeaderTimeout, IdleTimeout: mcpIdleConnection,
		ErrorLog: slog.NewLogLogger(log.Handler(), slog.LevelWarn),
	}}
}

func (c *httpComponent) Name() string { return c.name }

func (c *httpComponent) Start(ctx context.Context) error {
	ln, err := (&net.ListenConfig{}).Listen(ctx, "tcp", c.srv.Addr)
	if err != nil {
		return err
	}
	c.log.InfoContext(ctx, "serving", "addr", ln.Addr().String())
	go func() {
		if err := c.srv.Serve(ln); err != nil && !errors.Is(err, http.ErrServerClosed) {
			c.failed <- err
		}
	}()
	return nil
}

func (c *httpComponent) Stop(ctx context.Context) error { return c.srv.Shutdown(ctx) }

func (c *httpComponent) Failed() <-chan error { return c.failed }

// runComponent runs fn until the role stops; returning early is a failure.
type runComponent struct {
	name   string
	run    func(ctx context.Context) error
	close  func() error
	log    *slog.Logger
	cancel context.CancelFunc
	done   chan error
	failed chan error
}

func (c *runComponent) Name() string { return c.name }

func (c *runComponent) Start(context.Context) error {
	ctx, cancel := context.WithCancel(context.Background())
	c.cancel, c.done, c.failed = cancel, make(chan error, 1), make(chan error, 1)
	go func() {
		err := c.run(ctx)
		if ctx.Err() == nil {
			if err == nil {
				err = fmt.Errorf("%s returned before the role stopped", c.name)
			}
			c.failed <- err
		}
		c.done <- err
	}()
	return nil
}

func (c *runComponent) Stop(ctx context.Context) error {
	c.cancel()
	var err error
	select {
	case err = <-c.done:
	case <-ctx.Done():
		err = ctx.Err()
	}
	if c.close != nil {
		err = errors.Join(err, c.close())
	}
	return err
}

func (c *runComponent) Failed() <-chan error { return c.failed }
