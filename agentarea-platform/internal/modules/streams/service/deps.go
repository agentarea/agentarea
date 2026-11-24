package service

import (
	"context"
	"errors"
	"log/slog"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	kblob "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	identityapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
)

// Agents is what triggers read of agents: whether the workspace has the agent (agents' Lookup).
type Agents interface {
	AgentExists(ctx context.Context, ws scope.Workspace, id string) (bool, error)
}

// ModelKinds is the kind of a model instance the workspace sees (models' ModelKinds).
type ModelKinds interface {
	ModelKind(ctx context.Context, ws scope.Workspace, id string) (kind string, found bool, err error)
}

// AgentModels is the model instance an agent runs on (agents' Definitions).
type AgentModels interface {
	AgentModel(ctx context.Context, ws scope.Workspace, agentID string) (string, error)
}

// SourceTypes is catalog's source-type entries (registry_items of type source_types).
type SourceTypes = catalogapi.SourceTypes

// Secrets is the secret rows of a session's workspace, inside its transaction.
type Secrets interface {
	Manager(s db.Session, userID string) ksecrets.Manager
	Secret(ctx context.Context, s db.Session, id string) (ksecrets.Secret, bool, error)
	SecretNamed(ctx context.Context, s db.Session, name string) (ksecrets.Secret, bool, error)
	StageReferences(ctx context.Context, s db.Session, consumerType, consumerID string, refs []ksecrets.Reference) error
}

// SecretCatalog is the workspace secret catalog as one actor uses it (use checks, references).
type SecretCatalog func(ws scope.Workspace, actor ksecrets.Actor) ksecrets.Catalog

// Tasks is runs' task creation (TaskService.route_or_submit_task).
type Tasks = runsapi.Tasks

// TaskOutcomes is runs' read of the task a task event names.
type TaskOutcomes = runsapi.TaskOutcomes

// Turns records the delivery address of a follow-up routed into a running task: the turn it
// starts is answered there (replies.Turns).
type Turns interface {
	Begin(ctx context.Context, taskID string, address map[string]any) error
}

// Deps are the service's ports. A nil port leaves the routes that need it unmounted.
type Deps struct {
	DB    db.Database
	Graph authz.Graph
	// Agents answers whether an agent exists (agents module api).
	Agents Agents
	// ModelKinds, Models and AgentModels serve LLM conditions and LLM parameter extraction.
	ModelKinds  ModelKinds
	Models      runsapi.OneShotModels
	AgentModels AgentModels
	// Schedules keeps the cron schedules; nil leaves cron schedules unapplied and logged.
	Schedules durable.Scheduler
	// TriggerQueue is AGENTAREA_TRIGGER_QUEUE, the task queue cron schedules start their firings on.
	TriggerQueue string
	// SourceTypes is the catalog's source types.
	SourceTypes SourceTypes
	// Secrets is the secret store of a session's workspace (source credentials).
	Secrets Secrets
	// SecretCatalog checks a picked workspace secret is usable and records references.
	SecretCatalog SecretCatalog
	// Blob is the artifacts bucket: event bodies and attachments under the workspace's files.
	Blob kblob.Store
	// Bus publishes stream events to their partition.
	Bus events.Publisher
	// Broker reaches the live pub/sub channels and the raw streams.
	Broker events.Broker
	// Dedup is the event dedup cache (stream-event prefix).
	Dedup events.Dedup
	// Quota is the per-workspace event write quota.
	Quota WriteQuota
	// Tasks starts a trigger's task; nil leaves firing unmounted.
	Tasks Tasks
	// Turns records where a routed follow-up is answered; nil answers every turn of a session
	// at the message that started its task.
	Turns Turns
	// TaskReads is the task statuses and costs the feed and history show; nil shows none.
	TaskReads api.TaskReads
	// FiringTasks is the task reads a firing needs (retry, overlap, saved task); nil fails a firing that needs one.
	FiringTasks api.FiringTasks
	// TaskOutcomes reads the task a task event names (trigger outcomes, platform stream, replies).
	TaskOutcomes TaskOutcomes
	// Audit writes trigger.create|update|delete in the caller's transaction.
	Audit governanceapi.AuditWriter
	// APIURL is the public base of the webhook URLs (AGENTAREA_API_URL).
	APIURL string
	// WebhookURL overrides APIURL for webhook URLs (AGENTAREA_TELEGRAM_WEBHOOK_URL); empty for none.
	WebhookURL string
	// Settings are AGENTAREA_EVENT_* and AGENTAREA_TRIGGER_* values.
	Settings Settings
	// Out is the outbound HTTP clients: api_lookup reads a provider's API through netguard.Vendor.
	// Nil makes an api_lookup delivery unverifiable now (503).
	Out netguard.Clients
	// Fetchers bring the files an event names by reference, by its source type's
	// event.attachments.fetch; nil is the built-in ones over Out.
	Fetchers map[string]AttachmentFetcher
	// MCPEventSources reads an MCP server instance for an MCP Events source; nil refuses those sources.
	MCPEventSources MCPEventSources
	// TaskFiles reads a run's files: the files send_message sends. Nil refuses files.
	TaskFiles sandboxapi.TaskFiles
	// Links is identity's messenger link handshake; with Owners and Notices it admits the senders
	// of a source type with an admission. Nil refuses every such event.
	Links identityapi.MessengerLinks
	// Owners reads who owns a workspace (may_run).
	Owners identityapi.WorkspaceOwners
	// Notices is the once-a-day cache of what a refused sender was told (telegram-sender-notice).
	Notices events.Dedup
	// AppURL is the webapp's public base (AGENTAREA_APP_URL): where a sender links their account.
	AppURL string
	// Executor starts and cancels trigger batch workflows (signal-with-start); nil leaves batched
	// triggers erroring and open batches uncancelled.
	Executor durable.Executor
	// Now is the clock; nil is time.Now.
	Now func() time.Time
	Log *slog.Logger
}

// MCPEventInstance is what an MCP Events source reads of an MCP server instance.
type MCPEventInstance struct {
	AuthConfigID *string
	ManagedBy    *string
	// Events is the instance's stored events record (MCPServerInstance.events).
	Events map[string]any
}

// MCPEventSources is connections' MCP server instances of a workspace (app adapts its store).
type MCPEventSources interface {
	MCPEventSource(ctx context.Context, ws scope.Workspace, id string) (MCPEventInstance, bool, error)
}

// CodeRun is what the sandbox reports of one processor run; Stderr is read only when it failed.
type CodeRun struct {
	ExitCode        int
	Stdout          string
	StdoutTruncated bool
	Stderr          string
}

// ErrProcessorRuntimeUnavailable: the sandbox could not run the code; the event is redelivered.
var ErrProcessorRuntimeUnavailable = errors.New("the sandbox could not run the processor")

// ProcessorRunner runs a processor's bash command in the sandbox session session
// (processor_sandbox.SandboxCodeRunner); ErrProcessorRuntimeUnavailable when it cannot run at all.
type ProcessorRunner interface {
	Run(ctx context.Context, workspaceID, session, command string, timeout time.Duration, maxOutputBytes int) (CodeRun, error)
}

// WriteQuota is the sliding-window event quota of a workspace (write_quota.py).
type WriteQuota interface {
	// Admit takes one event of the workspace's per-minute limit; false when it is used up.
	Admit(ctx context.Context, workspaceID string, limit int) (bool, error)
}

// Settings are the stream and trigger settings (config/streams.py, config/triggers.py).
type Settings struct {
	Partitions     int
	WriteQuota     int
	ForwardDepth   int
	MaxAttempts    int
	BatchMaxEvents int
	WebhookRate    int
	// Retention is AGENTAREA_EVENT_RETENTION: how far back the events read model reaches.
	Retention time.Duration
}

// DefaultSettings are Python's defaults.
func DefaultSettings() Settings {
	return Settings{Partitions: 16, WriteQuota: 600, ForwardDepth: 8, MaxAttempts: 10, BatchMaxEvents: 100, WebhookRate: 100,
		Retention: 7 * 24 * time.Hour}
}
