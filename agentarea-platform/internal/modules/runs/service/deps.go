package service

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/analytics"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

// Principal is who an activity acts as: the run's agent in its workspace, for its user.
type Principal struct {
	WorkspaceID string
	UserID      string
	AgentID     string
}

// ErrNotFound: a definition a port was asked for does not exist (or is not visible).
var ErrNotFound = errors.New("not found")

// ErrRefused: a definition exists but may not be used by this run.
var ErrRefused = errors.New("refused")

// UnreachableError: a service the activity needs did not answer; the run
// waits out the outage (ServiceUnreachable).
type UnreachableError struct {
	Service string
	Err     error
}

func (e *UnreachableError) Error() string {
	return fmt.Sprintf("%s is unreachable: %v", e.Service, e.Err)
}
func (e *UnreachableError) Unwrap() error { return e.Err }

// TaskEvents is the broker side of a task's events: tasks.events for stored
// ones, pub/sub tasks.live.{task} for live-only signals, and the runner
// channel of a client.
type TaskEvents interface {
	Submit(ctx context.Context, e events.IntegrationEvent) error
	Broadcast(ctx context.Context, e events.IntegrationEvent) error
	NotifyRunner(ctx context.Context, clientID string, fields map[string]string) error
}

// ToolsRequest asks for the tools an agent's run may use.
type ToolsRequest struct {
	TaskID         string
	Agent          api.AgentSpec
	MCPInstanceIDs []string
	Policy         api.Policy
}

// ToolSet is every tool a run may call, with its binding; PolicyNames and
// RestrictingNames are filled by the resolver from the binding's identity.
type ToolSet struct {
	Tools                 []api.ToolDefinition
	SearchableTools       []api.SearchableTool
	ToolProviders         []api.ToolProvider
	Bindings              map[string]api.ToolBinding
	OpenAPIOperationTools map[string][]string
}

// InputsRequest names the files a run starts with.
type InputsRequest struct {
	TaskID               string
	FileIDs              []string
	TriggerEvent         map[string]any
	TriggerEventFileName string
}

// RunDefinitions are the reads resolve_run_config_activity makes, once, of
// other modules' definitions (connections/api, catalog/api, projects/api). ErrNotFound and ErrRefused are final; anything else is retried.
type RunDefinitions interface {
	Tools(ctx context.Context, p Principal, req ToolsRequest) (ToolSet, error)
	Skills(ctx context.Context, p Principal, agent api.AgentSpec, skillIDs []string) ([]api.Skill, []api.WithheldSkill, error)
	// ProjectInstructions are the run project's and its ancestors', root first.
	ProjectInstructions(ctx context.Context, p Principal, projectID string) ([]string, error)
	Inputs(ctx context.Context, p Principal, req InputsRequest) ([]api.InputFile, error)
}

// SkillFile is one file of a skill's package, by its path in the package.
type SkillFile struct {
	Path string
	Data []byte
}

// SkillPackages reads a skill's package by its pointer (catalog/api, GitHub
// over netguard). Allow returns ErrRefused when the install policy refuses,
// ErrNotFound when the skill is gone; ReadSkillMD returns ErrRefused when the
// package is unreadable.
type SkillPackages interface {
	Allow(ctx context.Context, p Principal, skill api.Skill) error
	ReadSkillMD(ctx context.Context, p Principal, skill api.Skill) (string, error)
	Files(ctx context.Context, p Principal, skill api.Skill) ([]SkillFile, error)
}

// RunnerTurn is one turn handed to the runner holding a client's socket.
type RunnerTurn struct {
	TaskID, AgentID, WorkspaceID string
	Iteration                    int
	TurnKey, Message             string
	ActorType, ActorID           string
}

// RunnerOutcome: Status is completed, failed or interrupted.
type RunnerOutcome struct{ Status, Response, Error string }

// RunnerSocket runs a turn on the client's runner (runs handlers, serve
// process). Each update frame the runner sends (runner_turn_update JSON) is
// passed to onUpdate while the turn runs.
type RunnerSocket interface {
	RunTurn(ctx context.Context, turn RunnerTurn, onUpdate func([]byte) error) (RunnerOutcome, error)
}

// ChargeLine is how a paid model call's spend line settles.
type ChargeLine struct {
	ModelInstanceID string
	Amount          money.Decimal
	Currency        string
	VendorCost      money.Decimal
	VendorCurrency  string
	Estimate        bool
	Settle          string
	HoldID          string
	CostUnknown     bool
	PlatformFunded  bool
	// Payer is platform or workspace, as the ledger reads it.
	Payer string
}

// Payment is one wallet payment a tool call made; Amount is in USD.
type Payment struct {
	Protocol       string
	Amount         money.Decimal
	Currency       string
	Network        string
	Reference      string
	Recipient      string
	TxHash         string
	IdempotencyKey string
	Settled        bool
	// AlreadySettled: an earlier attempt of the call paid it.
	AlreadySettled bool
}

// ToolProgress is a progress notice of a running tool.
type ToolProgress struct {
	Progress float64
	Total    *float64
	Message  string
}

// ToolImage is an image a tool returned; it is stored, never put in history.
type ToolImage struct {
	Data     []byte
	MimeType string
}

// ToolInvocation is one tool call for a binding.
type ToolInvocation struct {
	Principal   Principal
	TaskID      string
	ExecutionID string
	WorkflowID  string
	ToolCallID  string
	ToolName    string
	Args        map[string]any
	Binding     api.ToolBinding
	RunMetadata map[string]any
	// CallRef identifies the call on every retry; wallet payments key on it.
	CallRef  string
	Progress func(ToolProgress)
}

// ToolOutput is what a tool answered. MeteredBody and MeteredMeta are what
// the meter reads; VendorCost is a cost the connector reported for the call.
type ToolOutput struct {
	Success                  bool
	Result                   string
	Error                    string
	ExecutionTime            string
	ExitCode                 *int
	Outcome                  string
	ArtifactPaths            []string
	ServiceCost              money.Decimal
	ModelCost                money.Decimal
	ModelBilling             *ChargeLine
	CostUnknown              bool
	Payments                 []Payment
	Source                   string
	ServerInstanceID         string
	ServerName               string
	ServerIcon               string
	StructuredContent        any
	StructuredContentDropped bool
	MCPAppTool               string
	Images                   []ToolImage
	Replayed                 bool
	MeteredBody              any
	MeteredMeta              map[string]any
	VendorCost               *money.Decimal
	// RemoteTask is the task a remote delegate still runs; the answer comes when it ends.
	RemoteTask *api.RemoteAgentTask
}

// ToolCaller runs a call for one binding source: mcp (connections/api),
// openapi (connections/api, wallet/api for 402), code (the toolsets'
// modules), remote_agent (A2A).
type ToolCaller interface {
	Call(ctx context.Context, inv ToolInvocation) (ToolOutput, error)
}

// RemoteTaskCaller asks a remote delegate (remote_agent) about a task a call of it started.
// GetTask answers with RemoteTask set while the task still runs.
type RemoteTaskCaller interface {
	GetTask(ctx context.Context, inv ToolInvocation, task api.RemoteAgentTask) (ToolOutput, error)
	CancelTask(ctx context.Context, inv ToolInvocation, task api.RemoteAgentTask) error
}

// LLMGateCall is a model call as the entitlement gate sees it: the model the
// call resolved to, and whose credentials pay (ManagedBy "platform", or empty
// for the customer's own key).
type LLMGateCall struct {
	WorkspaceID, UserID, AgentID  string
	ModelID, ModelName, ManagedBy string
	ExecutionState                map[string]any
}

// VendorCosts are a connection's settled cost declaration and the credentialed
// GET that reads its vendor's figure (connections/api SettledCosts).
type VendorCosts interface {
	SettledDeclaration(ctx context.Context, ws scope.Workspace, userID, connectionID, tool string) (map[string]any, error)
	FetchSettlement(ctx context.Context, ws scope.Workspace, userID, connectionID, url string) (int, []byte, error)
}

// GateResult is the gate's verdict; Action is allow, deny, warn, escalate or modify.
type GateResult struct {
	Action          string
	InterceptorName string
	Reason          string
	Metadata        map[string]any
}

// EntitlementGate is the plan entitlement interceptor of PRE_LLM_CALL (factory.py, priority 120).
type EntitlementGate interface {
	CheckLLMCall(ctx context.Context, c LLMGateCall) (GateResult, error)
}

// Deps are what the run's activities need. Billing nil holds and charges
// nothing; Entitlement nil gates no model call; Telemetry nil records nothing.
type Deps struct {
	DB      db.Database
	Blob    blob.Store
	Events  TaskEvents
	Audit   governanceapi.AuditWriter
	Pricing money.CustomerPricing
	Billing money.ToolBilling
	Caps    governanceapi.Budgets
	// ToolCosts reads a connection's declared cost when a call is made; nil meters none.
	ToolCosts   api.ToolCosts
	Agents      agentsapi.Definitions
	Resolver    modelsapi.Resolver
	Definitions RunDefinitions
	Policies    governanceapi.RunPolicies
	Runtime     sandboxapi.Runtime
	Workspace   sandboxapi.TaskWorkspace
	Skills      SkillPackages
	Runner      RunnerSocket
	Models      modelsapi.Caller
	// CatalogAgents runs a catalog agent the workspace has not installed from its definition.
	CatalogAgents agentsapi.CatalogRuns
	// Describer and Decider serve the model calls made outside a run (OneShotModels).
	Describer modelsapi.Describer
	Decider   modelsapi.Decider
	// Media and VideoJobs serve the agentarea/media toolset.
	Media     modelsapi.Media
	VideoJobs modelsapi.VideoJobs
	Tools     map[string]ToolCaller
	// RemoteTasks reads and stops the tasks remote delegates run; nil leaves them unreachable.
	RemoteTasks RemoteTaskCaller
	// Web are the agentarea/web toolset's transports.
	Web         WebClients
	Settings    RunSettings
	Entitlement EntitlementGate
	Telemetry   RunTelemetry
	// ToolMetrics records the run's tool calls; nil records none.
	ToolMetrics *ToolTelemetry
	// Vendor reads what a settled tool call cost from its vendor (connections);
	// the settlement worker needs it.
	Vendor VendorCosts
	// Counter counts refused model calls for usage analytics; nil counts nothing.
	Counter analytics.Counter
	Now     func() time.Time
	Log     *slog.Logger
}

// BrokerEvents is TaskEvents over the kernel broker.
type BrokerEvents struct{ Broker events.Broker }

func (b BrokerEvents) Submit(ctx context.Context, e events.IntegrationEvent) error {
	fields, err := events.Encode(e)
	if err != nil {
		return err
	}
	_, err = b.Broker.Submit(ctx, events.TaskEvents, fields, events.BusRetention)
	return err
}

func (b BrokerEvents) Broadcast(ctx context.Context, e events.IntegrationEvent) error {
	if e.Subject == "" {
		return fmt.Errorf("live signal %s names no task", e.ID)
	}
	fields, err := events.Encode(e)
	if err != nil {
		return err
	}
	return b.Broker.Notify(ctx, events.TaskLiveChannel(e.Subject), fields)
}

func (b BrokerEvents) NotifyRunner(ctx context.Context, clientID string, fields map[string]string) error {
	return b.Broker.Notify(ctx, "clients."+clientID+".runner", fields)
}
