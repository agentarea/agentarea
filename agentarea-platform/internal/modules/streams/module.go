// Package streams is the streams module: streams, sources, subscriptions, stream events, triggers and their executions.
package streams

import (
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"net/http"
	"time"

	"log/slog"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	kblob "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/lifecycle"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	identityapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/handlers"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/router"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/serve"
)

// Deps are what streams needs from other modules and the kernel, as interfaces
// declared in its service/deps.go; app passes them in (rule 2).
type Deps struct {
	DB    db.Database
	Graph authz.Graph
	// Agents answers whether an agent exists (agents module api).
	Agents service.Agents
	// Schedules keeps the cron schedules; nil when Temporal is not wired.
	Schedules durable.Scheduler
	// TriggerQueue is AGENTAREA_TRIGGER_QUEUE.
	TriggerQueue string
	// SourceTypes is catalog's source types; nil leaves sources and the webhook sink unmounted.
	SourceTypes service.SourceTypes
	// Secrets and SecretCatalog hold source credentials by reference.
	Secrets       service.Secrets
	SecretCatalog service.SecretCatalog
	// Blob is the artifacts bucket (event bodies, attachments, download links).
	Blob kblob.Store
	// Bus, Broker and Dedup carry stream events and their live notices.
	Bus    events.Publisher
	Broker events.Broker
	Dedup  events.Dedup
	// Quota is the per-workspace event write quota.
	Quota service.WriteQuota
	// RateLimiter limits webhook deliveries per webhook id.
	RateLimiter httpx.RateLimiter
	// Out is the outbound HTTP clients (api_lookup verification).
	Out netguard.Clients
	// Guard is the outbound address policy an MCP Events subscriber's http callback must pass.
	Guard func() *netguard.Guard
	// MCPEventSources reads MCP server instances for MCP Events sources (connections' store).
	MCPEventSources service.MCPEventSources
	// ModelKinds, Models and AgentModels decide LLM conditions and extract LLM parameters.
	ModelKinds  service.ModelKinds
	Models      runsapi.OneShotModels
	AgentModels service.AgentModels
	// Links, Owners and Notices admit the senders of messenger sources; AppURL is where they link.
	Links   identityapi.MessengerLinks
	Owners  identityapi.WorkspaceOwners
	Notices events.Dedup
	AppURL  string
	// Tasks is runs' task creation; nil leaves run/execute and trigger firing unmounted.
	Tasks service.Tasks
	// Turns records where a follow-up routed into a running task is answered (replies.Turns).
	Turns service.Turns
	// TaskReads is runs' task statuses and costs; nil shows none.
	TaskReads api.TaskReads
	// FiringTasks is runs' task reads a firing needs (stored task, restart, open run, saved task).
	FiringTasks api.FiringTasks
	// TaskOutcomes is runs' read of the task a task event names; nil leaves the task-event
	// consumers (trigger outcomes, platform stream, replies) out.
	TaskOutcomes service.TaskOutcomes
	// Executor starts and cancels trigger batch workflows.
	Executor durable.Executor
	// Subscriber runs the router and events-view groups over streams.events; its delivery limit
	// must be Settings.MaxAttempts. nil leaves Consumers empty.
	Subscriber events.GroupSubscriber
	// Processors runs processor code in the sandbox; nil retries every processor reaction.
	Processors service.ProcessorRunner
	// TaskFiles reads a task's files: what a messenger reply and send_message send as files.
	TaskFiles sandboxapi.TaskFiles
	// Audit writes the trigger audit rows.
	Audit governanceapi.AuditWriter
	// APIURL and WebhookURL are the public bases of webhook URLs.
	APIURL     string
	WebhookURL string
	// Settings are the AGENTAREA_EVENT_* / AGENTAREA_TRIGGER_* values (LoadSettings).
	Settings service.Settings
	// Workspace admits the caller into /v1/workspaces/{workspace}.
	Workspace func(http.Handler) http.Handler
	Log       *slog.Logger
	Now       func() time.Time
}

// Module is streams, constructed once per process; a role picks which of its
// parts run.
type Module struct {
	d   Deps
	svc *service.Service
}

// New constructs the module.
func New(d Deps) *Module {
	if d.Settings == (service.Settings{}) {
		d.Settings = service.DefaultSettings()
	}
	return &Module{d: d, svc: service.New(service.Deps{
		DB: d.DB, Graph: d.Graph, Agents: d.Agents, Schedules: d.Schedules, TriggerQueue: d.TriggerQueue,
		SourceTypes: d.SourceTypes, Secrets: d.Secrets, SecretCatalog: d.SecretCatalog, Blob: d.Blob,
		Bus: d.Bus, Broker: d.Broker, Dedup: d.Dedup, Quota: d.Quota, Tasks: d.Tasks, Turns: d.Turns, Audit: d.Audit,
		TaskReads: d.TaskReads, FiringTasks: d.FiringTasks, TaskOutcomes: d.TaskOutcomes, Executor: d.Executor,
		APIURL: d.APIURL, WebhookURL: d.WebhookURL, Settings: d.Settings, Now: d.Now, Log: d.Log,
		Out: d.Out, MCPEventSources: d.MCPEventSources, ModelKinds: d.ModelKinds, Models: d.Models, AgentModels: d.AgentModels,
		Links: d.Links, Owners: d.Owners, Notices: d.Notices, AppURL: d.AppURL, TaskFiles: d.TaskFiles,
	})}
}

// Triggers is what other modules call on streams' triggers (agents' TaskDefTriggers, insights topology).
func (m *Module) Triggers() api.Triggers { return m.svc }

// TriggerExports lists the triggers for the workspace config export.
func (m *Module) TriggerExports() api.TriggerExports { return m.svc }

// Scheduling is the trigger side of the runs worker's schedule and trigger activities.
func (m *Module) Scheduling() *service.Scheduling { return m.svc.Scheduling() }

// Consumers are the worker's stream consumers: subscription changes, the events view and the router.
func (m *Module) Consumers() []lifecycle.Component {
	return router.Consumers(router.Deps{
		Service: m.svc, DB: m.d.DB, Subscriber: m.d.Subscriber, Broker: m.d.Broker, Runner: m.d.Processors,
		Settings: m.d.Settings, Now: m.d.Now, Log: m.d.Log,
	})
}

// Name is the module's name in the role table.
func (*Module) Name() string { return "streams" }

// Serve is the module's HTTP surface.
func (m *Module) Serve() serve.Module {
	return serve.Module{
		Name:   m.Name(),
		Errors: handlers.MapError,
		Mount: func(rt serve.Routes) error {
			handlers.Mount(rt.Mux.Chi(), rt.Errors, m.d.Workspace, handlers.New(m.svc, m.d.RateLimiter, m.d.Log))
			return nil
		},
	}
}
