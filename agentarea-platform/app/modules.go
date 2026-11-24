package app

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/redis/go-redis/v9"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/analytics"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	kblob "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	kevents "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	knetguard "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	kscope "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents"
	agentsservice "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections"
	connectionsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/runtime"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity"
	identityservice "github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/insights"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/projects"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs"
	runsservice "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/replies"
	streamsservice "github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/wallet"
	clusterauthn "github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/events"
	clusterhttpx "github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/serve"
)

// coreDeps are the kernel adapters and settings the core modules are built over.
type coreDeps struct {
	DB     db.Database
	Graph  authz.Graph
	APIURL string
	AppURL string
	Log    *slog.Logger
	Lookup config.Lookup
	// Connections is connections' loaded config.
	Connections connections.Config
	Broker      *events.Broker
	Redis       *redis.Client
	Blob        *blob.Client
	Secrets     *secrets.Factory
	Durable     *durable.Durable
	Extensions  *extensions
	Sandbox     sandbox.Config
	Outbound    *netguard.Outbound
	// Directory resolves Kratos identities (member removal, invitations).
	Directory identityservice.Directory
	// Counter is the process's analytics counter handle; it counts once insights' sender started.
	Counter *analytics.Handle
	// Mailer sends invitations; nil when the deployment has no SMTP.
	Mailer   identityservice.Mailer
	Agents   agents.Config
	Insights insights.Config
	// LiveTurns and TurnTokens are nil without AGENTAREA_MCP_GATEWAY_SECRET.
	LiveTurns  *clusterauthn.LiveTurns
	TurnTokens *clusterauthn.TurnTokens
	// MCPRuntime starts and retires MCP workloads in process; nil in a role
	// that calls no MCP tool (events).
	MCPRuntime *runtime.Runtime
	// RunSettings, Telemetry and ToolMetrics are the run activities' settings and metrics.
	RunSettings runsservice.RunSettings
	Telemetry   runsservice.RunTelemetry
	ToolMetrics *runsservice.ToolTelemetry
	Streams     streamsPlumbing
}

// streamsPlumbing is the stream event bus a role opened, its dedup and quota,
// and whether the role consumes it (the events role's router and views).
type streamsPlumbing struct {
	Bus        *kevents.Bus
	Dedup      *events.Dedup
	Notices    *events.Dedup
	Quota      streamsservice.WriteQuota
	Settings   streamsservice.Settings
	WebhookURL string
	Consume    bool
}

// moduleSet is every core module, built once per process over one coreDeps;
// each role picks the parts it runs.
type moduleSet struct {
	edge        *edge
	agents      *agents.Module
	connections *connections.Module
	governance  *governance.Module
	identity    *identity.Module
	sandbox     *sandbox.Module
	projects    *projects.Module
	catalog     *catalog.Module
	models      *models.Module
	insights    *insights.Module
	streams     *streams.Module
	wallet      *wallet.Module
	runsSurface *runs.Surface
	runner      *runs.RunnerSurface
	runs        *runs.Module
	streamsDeps streams.Deps
	toolsets    *connections.Toolsets
}

func (d coreDeps) secretCatalog(audit ksecrets.Auditor, ws kscope.Workspace, actor ksecrets.Actor) *secrets.Catalog {
	return secrets.NewCatalog(d.DB, d.Secrets, secrets.NewGuard(authz.NewPermissions(d.Graph, d.Log)), secrets.NewOwnership(d.Graph), audit, ws, actor)
}

// buildModules builds every core module once and passes each the others it
// declared. It wires e's admin authority to identity's owners.
func buildModules(e *edge, d coreDeps) *moduleSet {
	m := &moduleSet{edge: e}
	var artifacts, harness kblob.Store
	if d.Blob != nil {
		artifacts, harness = d.Blob.Artifacts(), d.Blob.Default()
	}
	m.agents = agents.New(func() agents.Deps {
		ad := agents.Deps{DB: d.DB, Graph: d.Graph, Config: d.Agents, Workspace: e.Workspace, Principal: e.Principal, Admin: e.Admin, Log: d.Log}
		ad.Secrets = delegateSecrets{d: d}
		ad.ClientAPIURL, ad.A2AAPIURL = d.APIURL, d.APIURL
		ad.A2APrincipal = func(ctx context.Context, token string) (*authn.Principal, error) {
			return e.gate.Optional(ctx, token, authn.SurfaceAPI, false)
		}
		ad.TaskDefTriggers = lateTriggers{m: m}
		ad.TaskDefRunner = lateTaskDefRunner{m: m}
		ad.Triggers, ad.CodeTools = lateAgentTriggers{m: m}, agentsservice.CodeCatalogue{}
		ad.Wallets = lateWalletCredentials{m: m}
		if artifacts != nil {
			ad.Blob = artifacts
		}
		if d.Outbound != nil {
			ad.SkillNet, ad.A2AOutbound = d.Outbound, d.Outbound.Transport(knetguard.Member)
		}
		if d.Redis != nil {
			ad.A2ARateLimiter = clusterhttpx.NewRateLimiter(d.Redis)
			ad.Presence = runs.NewRunnerPresence(d.Redis)
		}
		return ad
	}())
	m.connections = connections.New(func() connections.Deps {
		cd := connections.Deps{DB: d.DB, Graph: d.Graph, Secrets: d.Secrets,
			Catalog: func(ws kscope.Workspace, actor ksecrets.Actor) ksecrets.Catalog {
				return d.secretCatalog(nil, ws, actor)
			},
			Workspace: e.Workspace, Admin: e.Admin, Gate: e.gate, Authenticate: e.Principal,
			Agents: m.agents.AgentTools(), ClientBundles: m.agents.ClientBundles(), KV: connections.RedisKV(d.Redis),
			Config: d.Connections, APIURL: d.APIURL, AppURL: d.AppURL, Log: d.Log, Counter: d.Counter}
		if d.Outbound != nil {
			cd.Out = d.Outbound
		}
		if d.MCPRuntime != nil {
			cd.Runtime = d.MCPRuntime
		}
		if d.Redis != nil {
			cd.RateLimit = clusterhttpx.NewRateLimiter(d.Redis)
		}
		return cd
	}())
	gd := governance.Deps{DB: d.DB, Workspace: e.Workspace, Admin: e.Admin, Log: d.Log, Owners: governance.OwnersFrom(secrets.ResolveOwnerNames),
		Secrets: func(ws kscope.Workspace, actor ksecrets.Actor, audit ksecrets.Auditor) ksecrets.Catalog {
			return d.secretCatalog(audit, ws, actor)
		}}
	if d.Extensions != nil && d.Extensions.AuditSink != nil {
		gd.Sink = d.Extensions.AuditSink
	}
	if d.Extensions != nil && d.Extensions.EgressExits {
		gd.EgressExits = &governance.EgressExitPorts{Graph: d.Graph, Instances: m.connections.EgressBindings(),
			Upstream: func(ctx context.Context, rawURL string) error {
				if d.Outbound == nil {
					return errors.New("egress exits need the outbound address policy")
				}
				_, err := d.Outbound.Guard().CheckURL(ctx, rawURL)
				return err
			}}
	}
	gd.Tasks = lateTaskMetadata{m: m}
	m.governance = governance.New(gd)
	id := identity.Deps{
		DB: d.DB, Graph: d.Graph, Agents: m.agents.Lookup(),
		OnWorkspaceCreated: m.governance.ProvisionDefaults, Directory: d.Directory, Audit: m.governance.Audit(),
		Resources: explorerResources{lookup: m.agents.Lookup(), inventory: m.agents.Inventory(), mcp: lateMCPInventory{m: m}},
		Workspace: e.Workspace, Principal: e.Principal, Admin: e.Admin, Log: d.Log,
		Mailer: d.Mailer, AppURL: d.AppURL,
	}
	if artifacts != nil {
		id.Logos = artifacts
	}
	if d.Redis != nil {
		id.LinkCodes = identity.NewLinkCodes(redisSetEX{c: d.Redis})
	}
	m.identity = identity.New(id)
	e.admins = authz.NewAdmins(authz.WorkspaceScoped{}, m.identity.Owned(), d.Log)
	m.sandbox = sandbox.New(func() sandbox.Deps {
		sd := sandbox.Deps{
			DB: d.DB, Blob: artifacts, Harness: harness, Projects: func() sandbox.Projects { return m.projects.Lookup() },
			Config: d.Sandbox, APIURL: d.APIURL, Workspace: e.Workspace, Log: d.Log, Out: d.Outbound,
		}
		return sd
	}())
	m.projects = projects.New(projects.Deps{
		DB: d.DB, Agents: m.agents.Lookup(), Connections: m.connections.Lookup(),
		Files: m.sandbox.Files(), APIURL: d.APIURL, Workspace: e.Workspace,
	})
	m.catalog = catalog.New(catalogDeps(e, d, m))
	m.models = models.New(models.Deps{DB: d.DB, Catalog: m.catalog.Specs(), Secrets: secrets.NewSession(d.Secrets), Out: d.Outbound, Admin: e.Admin,
		Pricing: func() money.CustomerPricing { return d.Extensions.CustomerPricing }, LocalHost: models.LocalHost(d.Lookup),
		APIURL: d.APIURL, Principal: e.Principal, Workspace: e.Workspace})
	m.catalog.UseModels(m.models.SpecUse())
	m.agents.Use(agents.Later{Audit: m.governance.Audit(), ClientMCPNames: m.connections.Lookup(), ClientConnections: m.connections.Attachable(),
		Models: m.models.ModelKinds(), Connections: newAgentLoans(m.connections.Loans()),
		ClientRunnerKeys: clientRunnerKeys{k: m.identity.RunnerKeys()},
		Approvals:        m.governance.AgentApprovals(), Catalog: m.catalog.Installs(), InstallPolicy: m.governance.InstallPolicy()})
	m.connections.Use(connections.Later{Specs: m.catalog.MCPSpecs(), APIItems: m.catalog.APIItems(), Policies: m.governance.ToolPolicies(),
		Approvals: m.governance.ApprovalTargets(), Audit: m.governance.Audit(),
		Toolsets: m.platformToolsets(), EgressExits: m.governance.EgressExitBinding()})
	m.insights = insights.New(insights.Deps{DB: d.DB, Workspace: e.Workspace, Principal: e.Principal, Admin: e.Admin, Config: d.Insights, Log: d.Log,
		Balance: func() money.BalanceSource {
			if d.Extensions == nil {
				return nil
			}
			return d.Extensions.AccountBalance
		}(), Counter: d.Counter, Collector: vendorTransport(d.Outbound), Version: buildVersion()})
	m.runsSurface = newRunsSurface(e, d, runsProviders{Agents: m.agents, Governance: m.governance, Models: m.models, Sandbox: m.sandbox})
	m.connections.UseHeldCalls(m.runsSurface.HeldCalls())
	m.agents.UseA2A(m.runsSurface.A2A(), a2aPushSecrets{db: d.DB, f: d.Secrets}, func(ctx context.Context, rawURL string) error {
		_, err := d.Outbound.Guard().CheckURL(ctx, rawURL)
		return err
	})
	m.runner = runs.NewRunnerSurface(runs.RunnerDeps{DB: d.DB, Gate: e.gate, Clients: m.agents.RunnerClients(), Slugs: m.identity.WorkspaceSlugs(),
		Broker: d.Broker, Redis: d.Redis, Files: harness, Workers: d.Durable, Tokens: d.TurnTokens, Live: d.LiveTurns, Log: d.Log})
	m.streamsDeps = streamsDeps(e, d, m)
	m.streams = streams.New(m.streamsDeps)
	m.catalog.UseBundles(catalogBundles(d, m))
	m.agents.UseExport(exportWorkspaces{m: m.identity.Members()}, exportMCPs{x: m.connections.MCPExports()}, exportTriggers{x: m.streams.TriggerExports()})
	m.agents.UseToolsMCP(toolsMCP{x: m.connections.MCPToolCatalogue()})
	m.wallet = wallet.New(wallet.Deps{DB: d.DB, Agents: m.agents.Lookup(), Secrets: d.Secrets, Workspace: e.Workspace, Admin: e.Admin, Log: d.Log})
	m.connections.UseWallets(m.wallet.Wallets())
	m.runs = runs.New(runsDeps(d, m, harness))
	m.connections.UseClientCalls(m.runs.ClientToolCalls())
	m.insights.Use(insightsPorts(d, m))
	m.useLateToolsets()
	return m
}

func catalogDeps(e *edge, d coreDeps, m *moduleSet) catalog.Deps {
	cd := catalog.Deps{DB: d.DB, Authority: authz.WorkspaceScoped{}, Workspace: e.Workspace, Admin: e.Admin, Guard: d.Outbound.Guard, APIURL: d.APIURL, Log: d.Log,
		Secrets: func(ws kscope.Workspace, actor ksecrets.Actor) catalog.SecretUse {
			return d.secretCatalog(nil, ws, actor)
		},
		Uses: lateItemUses{m: m}, Credentials: registryCredentials(d.DB, d.Secrets), PlatformSecrets: platformSecrets{db: d.DB, f: d.Secrets},
		Mirror: m.agents.CatalogMirror()}
	cd.Connections = catalogConnections{x: m.connections.CatalogConnections()}
	pricing := catalogPricing{pricing: func() money.CustomerPricing { return money.USDAtProviderCost{} }, log: d.Log}
	if d.Extensions != nil {
		pricing.pricing = func() money.CustomerPricing { return d.Extensions.CustomerPricing }
		if d.Extensions.ToolBilling != nil {
			pricing.billing = d.Extensions.ToolBilling
		}
	}
	if d.MCPRuntime != nil {
		pricing.reservation = &reservationReader{read: d.MCPRuntime.Reservation, log: d.Log, now: time.Now}
	}
	cd.Pricing = pricing
	if d.Outbound != nil {
		cd.Net = d.Outbound
	}
	if d.Redis != nil {
		cd.RateLimit = clusterhttpx.NewRateLimiter(d.Redis)
	}
	return cd
}

func streamsDeps(e *edge, d coreDeps, m *moduleSet) streams.Deps {
	p := d.Streams
	sd := streams.Deps{DB: d.DB, Graph: d.Graph, Workspace: e.Workspace, Log: d.Log,
		SourceTypes: m.catalog.SourceTypes(), Secrets: secrets.NewSession(d.Secrets), Audit: m.governance.Audit(),
		SecretCatalog: func(ws kscope.Workspace, actor ksecrets.Actor) ksecrets.Catalog {
			return d.secretCatalog(nil, ws, actor)
		},
		Out: d.Outbound, APIURL: d.APIURL, WebhookURL: p.WebhookURL, Settings: p.Settings, Processors: processorRunner{p: m.sandbox.Processors()},
		Links: m.identity.MessengerLinks(), Owners: m.identity.WorkspaceOwners(), AppURL: d.AppURL,
		MCPEventSources: mcpEventSources{s: m.connections.MCPEventSources()}, TaskFiles: m.sandbox.TaskFiles(),
		ModelKinds: m.models.ModelKinds(), Models: lateOneShotModels{m: m}, AgentModels: agentModels{d: m.agents.Definitions()}}
	if d.Outbound != nil {
		sd.Guard = d.Outbound.Guard
	}
	streamsRunsPorts(&sd, m.runsSurface, m.agents)
	if d.Durable != nil {
		sd.Schedules, sd.Executor, sd.TriggerQueue = d.Durable.Scheduler(), d.Durable.Executor(), d.Durable.Config.Queues.Trigger
	}
	if d.Blob != nil {
		sd.Blob = d.Blob.Artifacts()
	}
	if d.Broker != nil {
		sd.Broker = d.Broker
	}
	if d.Redis != nil {
		sd.RateLimiter = clusterhttpx.NewRateLimiter(d.Redis)
		sd.Turns = replies.Turns{Redis: d.Redis}
	}
	if p.Bus != nil {
		sd.Bus, sd.Dedup, sd.Quota, sd.Notices = p.Bus, p.Dedup, p.Quota, p.Notices
		if p.Consume {
			sd.Subscriber = p.Bus
		}
	}
	return sd
}

// runsDeps are the runs worker's ports over the module set.
func runsDeps(d coreDeps, m *moduleSet, store kblob.Store) runs.Deps {
	svc := runsservice.Deps{
		DB: d.DB, Blob: store, Audit: m.governance.Audit(), Caps: m.governance.Budgets(), Policies: m.governance.RunPolicies(),
		ToolCosts: m.connections.ToolCosts(),
		Agents:    m.agents.Definitions(), CatalogAgents: m.agents.CatalogRuns(), Resolver: m.models.Resolver(), Models: m.models.Caller(),
		Describer: m.models.Describer(), Decider: m.models.Decider(), Media: m.models.Media(), VideoJobs: m.models.VideoJobs(),
		Runtime: m.sandbox.Runtime(), Workspace: m.sandbox.TaskWorkspace(),
		Tools: map[string]runsservice.ToolCaller{
			"mcp":          mcpCaller{t: m.connections.MCPTools()},
			"openapi":      openAPICaller{t: m.connections.OpenAPITools()},
			"code":         platformCaller{t: m.connections.PlatformTools()},
			"remote_agent": remoteAgentCaller{t: m.connections.RemoteAgents()},
		},
		RemoteTasks: remoteAgentCaller{t: m.connections.RemoteAgents()},
		Settings:    d.RunSettings, Telemetry: d.Telemetry, ToolMetrics: d.ToolMetrics, Log: d.Log,
		Definitions: newRunDefinitions(runTools{t: m.connections.RunTools()}, runSkillsPort{s: m.agents.RunSkills()},
			runInstructionsPort{p: m.projects.RunInstructions()}, runInputsPort{i: m.sandbox.RunInputs()}),
		Skills: skillPackages{s: m.agents.RunSkills()},
		Vendor: m.connections.SettledCosts(), Counter: d.Counter,
	}
	if d.Outbound != nil {
		svc.Web = runsservice.WebClients{Public: d.Outbound.Transport(knetguard.Public), Vendor: d.Outbound.Transport(knetguard.Vendor)}
	}
	if d.Broker != nil {
		svc.Events = runsservice.BrokerEvents{Broker: d.Broker}
	}
	if d.Extensions != nil {
		svc.Pricing = d.Extensions.CustomerPricing
		if d.Extensions.ToolBilling != nil {
			svc.Billing = d.Extensions.ToolBilling
		}
		if d.Extensions.EntitlementGuard != nil {
			svc.Entitlement = entitlementGate{g: d.Extensions.EntitlementGuard}
		}
	}
	scheduling := m.streams.Scheduling()
	rd := runs.Deps{Service: svc, Scheduling: runsservice.SchedulingDeps{
		Triggers: streamsTriggers{s: scheduling}, Batches: streamsBatches{s: scheduling}, Log: d.Log,
	}}
	if d.Durable != nil {
		rd.Executor, rd.AgentQueue = d.Durable.Executor(), d.Durable.Config.Queues.Agent
		rd.Scheduling.Schedules, rd.Scheduling.TriggerQueue = d.Durable.Scheduler(), d.Durable.Config.Queues.Trigger
	}
	return rd
}

// http is every core module's HTTP surface, mounted in this order, the edge first.
func (m *moduleSet) http() []serve.Module {
	return []serve.Module{m.edge.module(), m.identity.Serve(), m.connections.Serve(), m.projects.Serve(), m.agents.Serve(),
		m.catalog.Serve(), m.sandbox.Serve(), m.models.Serve(), m.governance.Serve(), m.runsSurface.Serve(), m.runner.Serve(),
		m.insights.Serve(), m.streams.Serve(), m.wallet.Serve()}
}

// lateTriggers is streams' trigger count for agents, which is built first.
type lateTriggers struct{ m *moduleSet }

func (t lateTriggers) CountByTaskDefinition(ctx context.Context, ws kscope.Workspace, definitionID string) (int64, error) {
	return t.m.streams.Triggers().CountByTaskDefinition(ctx, ws, definitionID)
}

// redisSetEX is identity's link code store over Redis.
type redisSetEX struct{ c *redis.Client }

func (r redisSetEX) SetEX(ctx context.Context, key, value string, ttl time.Duration) error {
	return r.c.Set(ctx, key, value, ttl).Err()
}

func (r redisSetEX) SetNX(ctx context.Context, key, value string, ttl time.Duration) (bool, error) {
	return r.c.SetNX(ctx, key, value, ttl).Result()
}

func (r redisSetEX) Del(ctx context.Context, key string) error {
	return r.c.Del(ctx, key).Err()
}

func (r redisSetEX) Get(ctx context.Context, key string) (string, error) {
	v, err := r.c.Get(ctx, key).Result()
	if errors.Is(err, redis.Nil) {
		return "", nil
	}
	return v, err
}

func (r redisSetEX) GetDel(ctx context.Context, key string) (string, error) {
	v, err := r.c.GetDel(ctx, key).Result()
	if errors.Is(err, redis.Nil) {
		return "", nil
	}
	return v, err
}

// vendorTransport is the transport to fixed third-party services; nil without outbound clients.
func vendorTransport(o *netguard.Outbound) http.RoundTripper {
	if o == nil {
		return nil
	}
	return o.Transport(knetguard.Vendor)
}

// mcpEventSources is connections' instances as streams' MCP Events sources read them.
type mcpEventSources struct {
	s connectionsapi.MCPEventSources
}

func (a mcpEventSources) MCPEventSource(ctx context.Context, ws kscope.Workspace, id string) (streamsservice.MCPEventInstance, bool, error) {
	inst, ok, err := a.s.MCPEventSource(ctx, ws, id)
	return streamsservice.MCPEventInstance{AuthConfigID: inst.AuthConfigID, ManagedBy: inst.ManagedBy, Events: inst.Events}, ok, err
}
