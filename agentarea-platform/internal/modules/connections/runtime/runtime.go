package runtime

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"sync"
	"time"

	"github.com/google/uuid"
	"go.opentelemetry.io/otel/metric"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/gateway"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/runtime/workload"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/service"
)

// Remote is a backend whose workloads are reached through it (the data plane).
type Remote interface {
	InstanceProxyURL(instanceID string) string
	Authorize(r *http.Request) bool
}

// StorageIssuer hands an instance that opts into storage its environment.
type StorageIssuer interface {
	Environment(instanceID, workspaceID string, spec map[string]any) (map[string]string, error)
}

// Validator is the backend's dry run of a json_spec (docker only).
type Validator func(ctx context.Context, spec map[string]any) (service.RuntimeValidation, error)

// Packages imports an npx/uvx package as an image.
type Packages interface {
	Import(ctx context.Context, instanceID string) (service.ImportedPackage, error)
}

// Deps is what the runtime is built over.
type Deps struct {
	Config  Config
	DB      db.Database
	Specs   catalogapi.MCPSpecs
	Secrets Secrets
	Backend workload.Backend
	// Remote is set when Backend is the data plane.
	Remote  Remote
	Storage StorageIssuer
	// Validator is nil on backends without a dry run.
	Validator Validator
	// Packages builds the package importer over the runtime; nil leaves
	// ImportPackage unconfigured.
	Packages func(rt *Runtime) (Packages, error)
	// Workloads reaches workloads and the data plane; URLs reaches url instances.
	Workloads http.RoundTripper
	URLs      http.RoundTripper
	// Extension points (ext.WorkloadHooks).
	SpecHook    SpecHook
	Participant LifecycleParticipant
	Observers   []Observer
	Requests    []gateway.RequestObserver
	Meter       metric.Meter
	Log         *slog.Logger
}

// Runtime is the MCP workload lifecycle.
type Runtime struct {
	d         Deps
	observer  observers
	telemetry *gateway.Telemetry
	reaps     metric.Int64Counter
	inProcess *gateway.Gateway
	packages  Packages

	mu       sync.Mutex
	failures map[string]failureState
}

var _ service.Runtime = (*Runtime)(nil)

var _ gateway.Runtime = (*Runtime)(nil)

// New checks d and builds the instruments.
func New(d Deps) (*Runtime, error) {
	switch {
	case d.DB == nil || d.Specs == nil || d.Secrets == nil || d.Backend == nil || d.Storage == nil:
		return nil, errors.New("MCP runtime needs a database, the catalog specs, secrets, a backend and a storage issuer")
	case d.Workloads == nil || d.URLs == nil || d.Meter == nil || d.Log == nil:
		return nil, errors.New("MCP runtime needs both transports, a meter and a logger")
	case len(d.Config.GatewaySecret) < minSecretLength:
		return nil, fmt.Errorf("MCP runtime needs AGENTAREA_MCP_GATEWAY_SECRET of at least %d bytes", minSecretLength)
	case d.Config.LeaseTTL <= 0 || d.Config.StartupTimeout <= 0 || d.Config.SweepInterval <= 0 || d.Config.IdleTimeout < 0:
		return nil, errors.New("MCP runtime lease, startup timeout and sweep interval must be positive and the idle timeout non-negative")
	case d.Config.BaseImage == "":
		return nil, errors.New("MCP runtime needs the mcp-base image")
	}
	t, err := gateway.NewTelemetry(d.Meter, d.Remote != nil)
	if err != nil {
		return nil, err
	}
	r := &Runtime{d: d, telemetry: t, failures: make(map[string]failureState)}
	r.observer = append(observers{&creationTelemetry{t: t, started: map[string]time.Time{}}}, d.Observers...)
	if err := r.instruments(); err != nil {
		return nil, err
	}
	if r.inProcess, err = r.newGateway(""); err != nil {
		return nil, err
	}
	if d.Packages != nil {
		if r.packages, err = d.Packages(r); err != nil {
			return nil, fmt.Errorf("MCP package importer: %w", err)
		}
	}
	return r, nil
}

func (r *Runtime) newGateway(secret string) (*gateway.Gateway, error) {
	var obs gateway.RequestObserver
	if len(r.d.Requests) > 0 {
		obs = requestObservers(r.d.Requests)
	}
	return gateway.New(gateway.Options{Runtime: r, Secret: secret, LeaseTTL: r.d.Config.LeaseTTL,
		Workloads: r.d.Workloads, URLs: r.d.URLs, Observer: obs, Telemetry: r.telemetry, Log: r.d.Log})
}

// Gateway is the data path for this process's own callers: it requires no
// manager authorization and is never mounted on a listener.
func (r *Runtime) Gateway() http.Handler { return r.inProcess }

// ServedGateway is the data path the mcp role serves to other processes,
// behind AGENTAREA_MCP_GATEWAY_SECRET.
func (r *Runtime) ServedGateway() (*gateway.Gateway, error) {
	return r.newGateway(r.d.Config.GatewaySecret)
}

// Load resolves an instance for the gateway.
func (r *Runtime) Load(ctx context.Context, instanceID string) (gateway.Target, error) {
	l, err := r.load(ctx, instanceID)
	if err != nil {
		return gateway.Target{}, err
	}
	return l.target, nil
}

func (r *Runtime) loadContainer(ctx context.Context, instanceID string) (*instance, error) {
	l, err := r.load(ctx, instanceID)
	if err != nil {
		return nil, err
	}
	if l.container == nil {
		return nil, fmt.Errorf("instance %s is not a container-backed MCP server", instanceID)
	}
	return l.container, nil
}

// Admit starts the workload when it is not running, under the instance's
// lifecycle lock, and opens the request's lease.
func (r *Runtime) Admit(ctx context.Context, t gateway.Target, requestID string, report *gateway.ColdStart) (gateway.Admission, error) {
	id, err := parseID(t.InstanceID)
	if err != nil {
		return gateway.Admission{}, err
	}
	rid, err := uuid.Parse(requestID)
	if err != nil {
		return gateway.Admission{}, fmt.Errorf("request id: %w", err)
	}
	inst, err := r.loadContainer(ctx, t.InstanceID)
	if err != nil {
		return gateway.Admission{}, err
	}
	startCtx, cancel := context.WithTimeout(ctx, r.d.Config.StartupTimeout)
	defer cancel()
	var upstream string
	err = r.withInstanceLock(startCtx, t.InstanceID, func(ctx context.Context) error {
		defer func(began time.Time) { report.Total = time.Since(began) }(time.Now())
		if err := r.markStarting(ctx, id); err != nil {
			return err
		}
		var err error
		upstream, err = r.ensureReady(ctx, inst, report)
		if err != nil {
			fctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), failureMarkTimeout)
			defer cancel()
			if markErr := r.markFailed(fctx, id, err); markErr != nil {
				r.d.Log.Error("could not record MCP start failure", "instance_id", t.InstanceID, "error", markErr)
			}
			return err
		}
		if err := r.markReadyAndBeginRequest(ctx, id, rid); err != nil {
			report.Fail(gateway.StepAdmission)
			fctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), failureMarkTimeout)
			defer cancel()
			return errors.Join(err, r.remove(fctx, inst), r.markFailed(fctx, id, err))
		}
		return nil
	})
	if err != nil {
		return gateway.Admission{}, err
	}
	adm := gateway.Admission{Upstream: upstream, Lease: &lease{r: r, id: id, request: rid}}
	if r.d.Remote != nil {
		adm.Remote, adm.Authorize = true, r.d.Remote.Authorize
	}
	return adm, nil
}

type lease struct {
	r       *Runtime
	id      uuid.UUID
	request uuid.UUID
}

func (l *lease) Heartbeat(ctx context.Context) error { return l.r.heartbeat(ctx, l.request) }

func (l *lease) Finish(ctx context.Context) error { return l.r.finishRequest(ctx, l.id, l.request) }

// URLHeaders resolves a url instance's headers: literals and workspace secret
// references, then its own env_vars secrets, which win.
func (r *Runtime) URLHeaders(ctx context.Context, t gateway.Target) (map[string]string, error) {
	if t.URL == nil {
		return nil, fmt.Errorf("instance %s is not a url instance", t.InstanceID)
	}
	return r.resolveSecrets(ctx, t.WorkspaceID, t.InstanceID, t.URL.Headers, t.URL.EnvVars)
}

// Retire stops the instance's workload (DELETE /mcp/{id}). service callers
// get a *service.RuntimeRetirementError when the desired state is unchanged.
func (r *Runtime) Retire(ctx context.Context, instanceID string) error {
	err := r.retireForDeletion(ctx, instanceID)
	switch {
	case err == nil:
		return nil
	case errors.Is(err, gateway.ErrInstanceBusy), errors.Is(err, gateway.ErrStartInProgress):
		return &retirementError{conflict: true, err: err}
	default:
		return &retirementError{err: err}
	}
}

// retirementError is a service.RuntimeRetirementError the gateway still
// classifies by its cause.
type retirementError struct {
	conflict bool
	err      error
}

func (e *retirementError) Error() string { return e.err.Error() }

func (e *retirementError) Unwrap() error { return e.err }

// As lets callers ask for the service's error type.
func (e *retirementError) As(target any) bool {
	t, ok := target.(**service.RuntimeRetirementError)
	if ok {
		*t = &service.RuntimeRetirementError{Conflict: e.conflict, Msg: e.err.Error()}
	}
	return ok
}

// Health reports the workload (GET /instances/{id}/health).
func (r *Runtime) Health(ctx context.Context, instanceID string) (service.RuntimeHealth, error) {
	st, err := r.d.Backend.Status(ctx, instanceID)
	if errors.Is(err, workload.ErrNotFound) {
		return service.RuntimeHealth{}, service.ErrRuntimeNotRunning
	}
	if err != nil {
		return service.RuntimeHealth{}, err
	}
	if !ready(st.Status) {
		return service.RuntimeHealth{Healthy: false, Status: st.Status}, nil
	}
	if r.d.Remote != nil || st.InternalURL == "" {
		return service.RuntimeHealth{Healthy: true, Status: st.Status}, nil
	}
	if err := waitListening(ctx, st.InternalURL, time.Now().Add(healthDialTimeout)); err != nil {
		return service.RuntimeHealth{Healthy: false, Status: "unreachable"}, nil
	}
	return service.RuntimeHealth{Healthy: true, Status: st.Status}, nil
}

const healthDialTimeout = 3 * time.Second

// Validate is the backend's dry run of a json_spec.
func (r *Runtime) Validate(ctx context.Context, name string, jsonSpec map[string]any) (service.RuntimeValidation, error) {
	if r.d.Validator == nil {
		return service.RuntimeValidation{}, errors.New("the MCP runtime's backend has no dry-run validation")
	}
	v, err := r.d.Validator(ctx, plainNumbers(jsonSpec).(map[string]any))
	if err != nil {
		r.d.Log.Error("MCP dry-run validation failed", "name", name, "error", err)
	}
	return v, err
}

// plainNumbers turns json.Number into float64, the shape the dry run reads.
func plainNumbers(v any) any {
	switch t := v.(type) {
	case map[string]any:
		out := make(map[string]any, len(t))
		for k, x := range t {
			out[k] = plainNumbers(x)
		}
		return out
	case []any:
		out := make([]any, len(t))
		for i, x := range t {
			out[i] = plainNumbers(x)
		}
		return out
	case json.Number:
		if f, err := t.Float64(); err == nil {
			return f
		}
		return t.String()
	default:
		return v
	}
}

// ImportPackage converts a command instance's npx/uvx package into an image.
func (r *Runtime) ImportPackage(ctx context.Context, instanceID string) (service.ImportedPackage, error) {
	if r.packages == nil {
		return service.ImportedPackage{}, errors.New("MCP package import is not configured")
	}
	return r.packages.Import(ctx, instanceID)
}

// Workload is the spec a command instance would start with, secrets
// resolved, without starting it (the package importer's input).
func (r *Runtime) Workload(ctx context.Context, instanceID string) (workload.Spec, map[string]any, error) {
	inst, err := r.loadContainer(ctx, instanceID)
	if err != nil {
		return workload.Spec{}, nil, err
	}
	spec, err := r.buildSpec(ctx, inst)
	return spec, inst.Spec, err
}

// StorageInstance is what the storage API reads of an instance.
func (r *Runtime) StorageInstance(ctx context.Context, instanceID string) (string, map[string]any, error) {
	l, err := r.load(ctx, instanceID)
	if err != nil {
		return "", nil, err
	}
	if l.container == nil {
		return l.target.WorkspaceID, map[string]any{}, nil
	}
	return l.target.WorkspaceID, l.container.Spec, nil
}

// Reservation is what one default workload reserves on the backend.
func (r *Runtime) Reservation(ctx context.Context) (workload.Reservation, error) {
	return r.d.Backend.Reservation(ctx)
}

// Run reaps idle workloads every sweep interval until ctx ends; an idle
// timeout of zero disables reaping.
func (r *Runtime) Run(ctx context.Context) error {
	if r.d.Config.IdleTimeout == 0 {
		<-ctx.Done()
		return nil
	}
	t := time.NewTicker(r.d.Config.SweepInterval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return nil
		case <-t.C:
			if _, err := r.Reap(ctx); err != nil && ctx.Err() == nil {
				r.d.Log.Error("MCP idle sweep failed", "error", err)
			}
		}
	}
}

// Reap retires every idle workload once; it reports how many it removed.
func (r *Runtime) Reap(ctx context.Context) (int, error) {
	ids, err := r.idleCandidates(ctx)
	if err != nil {
		return 0, err
	}
	reaped := 0
	for _, id := range ids {
		removed, err := r.reapIfIdle(ctx, id)
		if errors.Is(err, gateway.ErrStartInProgress) {
			continue
		}
		if err != nil {
			r.d.Log.Warn("failed to reap idle MCP instance", "instance_id", id.String(), "error", err)
			continue
		}
		if removed {
			reaped++
			r.reaps.Add(ctx, 1)
		}
	}
	return reaped, nil
}

type requestObservers []gateway.RequestObserver

func (o requestObservers) Started(ctx context.Context, rs gateway.RequestStarted) error {
	for _, obs := range o {
		if err := obs.Started(ctx, rs); err != nil {
			return err
		}
	}
	return nil
}

func (o requestObservers) Completed(ctx context.Context, rc gateway.RequestCompleted) error {
	errs := make([]error, 0, len(o))
	for _, obs := range o {
		errs = append(errs, obs.Completed(ctx, rc))
	}
	return errors.Join(errs...)
}
