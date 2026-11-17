package ext

import (
	"context"
	"io/fs"
	"log/slog"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// Kernel types an extension speaks, aliased so the enterprise module uses
// them without importing internal/.
type (
	Workspace = scope.Workspace
	Caller    = authn.Caller
	Principal = authn.Principal
	Decimal   = money.Decimal
	Currency  = money.Currency
	Router    = httpx.Router
	Loader    = config.Loader

	Middleware = httpx.Middleware
	Errors     = httpx.Errors
	FieldError = httpx.FieldError

	Database = db.Database
	Querier  = db.Querier
	Session  = db.Session
	LockKey  = db.LockKey

	ToolBilling      = money.ToolBilling
	AuthorizeRequest = money.AuthorizeRequest
	CaptureRequest   = money.CaptureRequest
	HoldDecision     = money.HoldDecision
	Charge           = money.Charge
	QuoteLine        = money.QuoteLine
	Quote            = money.Quote
	BillingKind      = money.BillingKind

	CustomerPricing = money.CustomerPricing
	ComputePricing  = money.ComputePricing

	AccountBalance       = money.AccountBalance
	AccountBalanceSource = money.BalanceSource
	WorkspaceUsage       = money.WorkspaceUsage
	WorkspaceUsageSource = money.UsageSource
)

// Deps is what a factory may use.
type Deps struct {
	Logger *slog.Logger
	// Config reads the extension's own variables; call Err after loading.
	Config *Loader
	// DB is the one database of the core (AGENTAREA_DB_*), shared with it.
	DB Database
	// Secrets resolves workspace secrets (AGENTAREA_SECRET_*); nil in a
	// process without the database.
	Secrets WorkspaceSecrets
	// Errors renders a handler's error as the core renders its own
	// (problem+json). Set for route factories only.
	Errors *Errors
	// Authenticate resolves the caller's principal or answers 401; behind it
	// PrincipalFrom holds. Account routes declare no auth of their own, so a
	// route that needs a principal wraps itself in it. Set for route
	// factories only.
	Authenticate Middleware
	// RequireAdmin refuses a caller who does not administer the workspace it
	// acts in (403, requires_workspace_admin). Set for route factories only.
	RequireAdmin func(ctx context.Context, c Caller) error
}

// CallerFrom returns the caller of a workspace route.
func CallerFrom(ctx context.Context) (Caller, bool) { return authn.CallerFrom(ctx) }

// NewLoader reads configuration through lookup (os.LookupEnv in the core),
// for testing factories outside a role.
func NewLoader(lookup func(string) (string, bool)) *Loader { return config.New(lookup) }

// WithCaller stores the caller of a workspace route, as the core's edge does.
func WithCaller(ctx context.Context, c Caller) context.Context { return authn.WithCaller(ctx, c) }

// WithPrincipal stores an authenticated principal, as Deps.Authenticate does.
func WithPrincipal(ctx context.Context, p Principal) context.Context {
	return authn.WithPrincipal(ctx, p)
}

// PrincipalFrom returns the principal Deps.Authenticate resolved.
func PrincipalFrom(ctx context.Context) (Principal, bool) { return authn.PrincipalFrom(ctx) }

// HTTPError is Starlette's HTTPException(status, detail): problem+json with
// code http_error, rendered by Deps.Errors.
func HTTPError(status int, detail string) error { return httpx.HTTPError(status, detail) }

// Validation is FastAPI's request validation error (422 with the field
// errors), nil when errs is empty.
func Validation(errs ...FieldError) error { return httpx.Validation(errs...) }

// ErrComputeUnpriced is ComputePricing's answer while billing prices no
// compute.
var ErrComputeUnpriced = money.ErrComputeUnpriced

// ErrBillingRejected is money.ErrBillingRejected: wrap it in a ToolBilling error for a request billing refuses as such.
var ErrBillingRejected = money.ErrBillingRejected

// NewErrors is the core's error renderer, for testing route extensions
// outside serve; apiURL is AGENTAREA_API_URL.
func NewErrors(apiURL string, log *slog.Logger) *Errors { return httpx.NewErrors(apiURL, log) }

// TextLockKey is the advisory lock hashtextextended(text, 0).
func TextLockKey(text string) LockKey { return db.TextKey(text) }

// NewWorkspace names a workspace by id for a session opened outside HTTP.
func NewWorkspace(id string) (Workspace, error) { return scope.NewWorkspace(id, "") }

// Phase is where an interceptor runs (governance domain/enums.py Phase).
type Phase string

const (
	PhasePreLLMCall     Phase = "pre_llm_call"
	PhasePostLLMCall    Phase = "post_llm_call"
	PhasePreToolCall    Phase = "pre_tool_call"
	PhasePostToolCall   Phase = "post_tool_call"
	PhasePreDelegation  Phase = "pre_delegation"
	PhasePostDelegation Phase = "post_delegation"
	PhaseToolDiscovery  Phase = "tool_discovery"
)

// InterceptorCategory is how the pipeline runs an interceptor.
type InterceptorCategory string

const (
	CategoryGate     InterceptorCategory = "gate"
	CategoryFilter   InterceptorCategory = "filter"
	CategoryObserver InterceptorCategory = "observer"
)

// InterceptorAction is an interceptor's decision.
type InterceptorAction string

const (
	ActionAllow    InterceptorAction = "allow"
	ActionDeny     InterceptorAction = "deny"
	ActionWarn     InterceptorAction = "warn"
	ActionEscalate InterceptorAction = "escalate"
	ActionModify   InterceptorAction = "modify"
)

// InterceptorContext is everything an interceptor decides on
// (domain/models.py). AgentID is empty when no agent calls.
type InterceptorContext struct {
	AgentID        string
	WorkspaceID    string
	UserID         string
	Phase          Phase
	ActionType     string
	ActionName     string
	ActionParams   map[string]any
	Content        *string
	ExecutionState map[string]any
	// Model is the model a PRE_LLM_CALL resolved to (resolved_model); nil
	// when none was resolved.
	Model *CallModel
}

// CallModel is what an LLM call is about to spend: the model instance and
// whose credentials pay. ManagedBy is ManagedByPlatform on the deployment's
// credentials and empty on the customer's own.
type CallModel struct {
	ModelID   string
	ModelName string
	ManagedBy string
}

// ManagedByPlatform is CallModel.ManagedBy on the deployment's credentials.
const ManagedByPlatform = "platform"

// DetectionFinding is one finding of a detection engine.
type DetectionFinding struct {
	Category    string
	MatchedText string
	Span        [2]int
	Confidence  float64
	EngineName  string
}

// InterceptorResult is an interceptor's answer.
type InterceptorResult struct {
	Action          InterceptorAction
	InterceptorName string
	Reason          string
	ModifiedContent *string
	Findings        []DetectionFinding
	Metadata        map[string]any
}

// EntitlementGuard is a governance ExecutionInterceptor (domain/protocols.py),
// registered as a gate at PRE_LLM_CALL.
type EntitlementGuard interface {
	Name() string
	Category() InterceptorCategory
	Execute(ctx context.Context, ic InterceptorContext) (InterceptorResult, error)
}

// EgressExits is what entry point "egress_exits" (egress_exits_enforced)
// builds: the edition seals the exit an MCP instance binds into its workload
// (WorkloadHooks.MCPWorkload) and its egress exit proxy routes it. Being
// built is what opens the egress exits API and the binding of exits.
type EgressExits struct{}

// WorkspaceSecrets resolves a workspace's secret by its stored name, at the
// moment of use.
type WorkspaceSecrets interface {
	WorkspaceSecret(ctx context.Context, workspaceID, name string) (string, error)
}

// AuditSink receives every recorded audit event as the audit_events row's
// dict (AuditEventORM.to_dict). A failing Emit is logged, never fatal.
type AuditSink interface {
	Emit(ctx context.Context, event map[string]any) error
}

// WorkloadHooks is the mcp-manager and sandbox-runner overlay's composition
// bundle, read by every process that runs MCP workloads or sandboxes: the mcp
// and sandbox roles, a data-plane host, and serve, worker and all, which start
// MCP workloads themselves. Every field is optional.
type WorkloadHooks struct {
	// Attach runs once, after the process built what it runs and before it
	// serves or calls any other hook; an error stops the process.
	Attach func(ctx context.Context, w Workloads) error
	// Run starts after every component is built and before traffic is
	// accepted; returning before the role is asked to stop is a failure. It
	// runs in the mcp role, a data-plane host and all.
	Run func(ctx context.Context) error
	// Close runs after Run returned and before core connections close.
	Close func() error
	// HostRoutes adds routes inside the authenticated group of a remote
	// workload host (managerapp Options.DataPlane).
	HostRoutes RouteFactory
	// MCPWorkload rewrites an MCP workload before it starts (the egress
	// binding); an error refuses the start.
	MCPWorkload func(ctx context.Context, instanceID, workspaceID string, w *MCPWorkload) error
	// MCPLifecycle runs inside every MCP lifecycle transition's transaction;
	// an error rolls the transition back.
	MCPLifecycle func(ctx context.Context, q Querier, c MCPLifecycleChange) error
	// MCPRequests sees every request through the MCP gateway; a Started
	// error refuses the request with 503.
	MCPRequests MCPRequestObserver
	// MCPOperations sees MCP workload creations, deletions and boundaries;
	// an error on a started creation refuses the start.
	MCPOperations MCPOperationObserver
	// Sandboxes sees an external sandbox provider's sessions.
	Sandboxes SandboxObserver
	// TaskPods sees the Kubernetes built-in sandbox's task pods.
	TaskPods TaskPodObserver
	// Artifacts sees every artifact publication.
	Artifacts ArtifactObserver
}

// MCPWorkload is the part of an MCP workload a hook may change, and what
// its instance's merged json_spec says of egress, which it may not: the exit
// it names ("" for none) and whether its server requires one
// (json_spec.egress.required).
type MCPWorkload struct {
	Environment    map[string]string
	Labels         map[string]string
	EgressExit     string
	EgressRequired bool
}

// MCPLifecycleChange is the lifecycle row a transition left. Transition is
// starting, ready, failed, retiring, retirement_failed or retired; Reason is
// demand, activation, idle or deletion.
type MCPLifecycleChange struct {
	InstanceID  string
	WorkspaceID string
	Generation  int64
	State       string
	Transition  string
	Reason      string
	UpdatedAt   time.Time
}

// MCPRequest is one request through the MCP gateway.
type MCPRequest struct {
	RequestID   string
	InstanceID  string
	WorkspaceID string
	Method      string
	MCPMethod   *string
	MCPName     *string
	StartedAt   time.Time
}

// MCPRequestDone is a finished request. Answer is "starting" or
// "start_failed" when the gateway answered itself; ColdStart is set when the
// request started the workload.
type MCPRequestDone struct {
	MCPRequest
	EndedAt    time.Time
	StatusCode int
	Canceled   bool
	Answer     string
	ColdStart  *MCPColdStart
}

// MCPColdStart is a workload activation: Outcome ready, failed or timeout.
type MCPColdStart struct {
	Outcome   string
	Reason    string
	Running   time.Duration
	Listening time.Duration
	Total     time.Duration
}

// MCPRequestObserver sees the gateway's requests.
type MCPRequestObserver interface {
	Started(ctx context.Context, r MCPRequest) error
	Completed(ctx context.Context, r MCPRequestDone) error
}

// MCPOperation is one phase (started, completed, failed) of a workload
// creation or deletion.
type MCPOperation struct {
	InstanceID  string
	WorkspaceID string
	OperationID string
	Kind        string
	Phase       string
	ObservedAt  time.Time
}

// MCPBoundary is a point a workload's existence changes at: activation,
// creation_failed, deletion or failed_start_cleanup.
type MCPBoundary struct {
	InstanceID  string
	WorkspaceID string
	OperationID string
	Boundary    string
}

// MCPOperationObserver sees workload operations.
type MCPOperationObserver interface {
	Operation(ctx context.Context, o MCPOperation) error
	Boundary(ctx context.Context, b MCPBoundary) error
}

// MigrationSet is an embedded goose migration directory applied after the
// core set, in the order registered. Its objects live in Schema, created when
// absent; its goose table is <Schema>.goose_db_version. A database built by
// the Python migrations of the set must stand at AlembicHead in AlembicTable
// (schema-qualified); the baseline is then recorded, not run.
type MigrationSet struct {
	Name         string
	FS           fs.FS
	Schema       string
	AlembicTable string
	AlembicHead  string
}

// Command is a one-shot subcommand: agentarea <Name> [args].
type Command struct {
	Name    string
	Summary string
	Run     func(ctx context.Context, deps Deps, args []string) error
}

// Role is a long-running subcommand with its own deployment.
type Role struct {
	Name    string
	Summary string
	Run     func(ctx context.Context, deps Deps) error
}
