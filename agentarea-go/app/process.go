package app

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"os"
	"strconv"
	"strings"

	"github.com/agentarea/agentarea/agentarea-go/api/openapi"
	"github.com/agentarea/agentarea/agentarea-go/ext"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/analytics"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	kdurable "github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
	kevents "github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/lifecycle"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	knetguard "github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/insights"
	runsservice "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/delivery"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/polling"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/quota"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/replies"
	streamsservice "github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster"
	"github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster/durable"
	"github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster/events"
	"github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/serve"
)

// parts are what a process runs of the module set: the HTTP API, the
// Temporal workers, the stream consumers. The all role runs every part.
type parts struct {
	serve, worker, events, operator bool
	// reconcile runs the catalog reconcile once, then the process exits.
	reconcile *catalogapi.ReconcileOptions
	// job runs once over the module set, then the process exits.
	job func(ctx context.Context, m *moduleSet) error
}

func (b *Build) runServe(ctx context.Context) error {
	return b.runParts(ctx, "serve", parts{serve: true})
}
func (b *Build) runWorker(ctx context.Context) error {
	return b.runParts(ctx, "worker", parts{worker: true})
}
func (b *Build) runEvents(ctx context.Context) error {
	return b.runParts(ctx, "events", parts{events: true})
}
func (b *Build) runAll(ctx context.Context) error {
	return b.runParts(ctx, "all", parts{serve: true, worker: true, events: true})
}

// runParts builds the one module set over the cluster profile and runs the
// lifecycle components of p. A part whose ports have no implementation
// refuses to start, naming them.
func (b *Build) runParts(ctx context.Context, name string, p parts) (err error) {
	l := config.New(b.lookup)
	common := config.LoadCommon(l)
	cfg := serve.LoadConfig(l)
	pcfg := cluster.LoadConfig(l)
	sandboxCfg := sandbox.LoadConfig(l)
	spend := money.LoadSpendCurrency(l)
	outCfg := knetguard.LoadConfig(l)
	identityCfg := identity.LoadConfig(l)
	agentsCfg := agents.LoadConfig(l)
	insightsCfg := insights.LoadConfig(l)
	runSettings := runsservice.LoadRunSettings(l)
	webhookURL, _ := l.OptionalEnv("AGENTAREA_TELEGRAM_WEBHOOK_URL")
	callsTools := p.serve || p.worker
	var health *processHealth
	var healthAddr string
	switch {
	case p.serve:
	case p.worker:
		health, healthAddr = &processHealth{}, net.JoinHostPort("", strconv.Itoa(l.IntEnv("AGENTAREA_WORKER_HEALTH_PORT", 8081)))
	case p.events:
		health, healthAddr = &processHealth{}, cfg.Addr
	}
	var mcpCfg mcpConfig
	if callsTools {
		mcpCfg = loadMCPConfig(l)
	}
	var pollCfg polling.Config
	var replyCfg replies.Config
	if p.events {
		pollCfg = polling.LoadConfig(l, os.Hostname)
		replyCfg = replies.LoadConfig(l)
		if pcfg.Authn.GatewaySecret == "" {
			l.Fail("AGENTAREA_MCP_GATEWAY_SECRET", errors.New("is required: the pollers call MCP Events through the MCP manager"))
		}
	}
	if err := l.Err(); err != nil {
		return fmt.Errorf("configuration: %w", err)
	}
	pcfg.OTel, pcfg.Service, pcfg.Version, pcfg.Environment = common.OTelEnabled, "agentarea-"+name, buildVersion(), common.Env
	pcfg.Getenv = func(n string) string { v, _ := b.lookup(n); return v }
	log := newLogger(b.stderr, common).With("component", name)
	profile, err := cluster.Open(ctx, pcfg, log)
	if err != nil {
		return err
	}
	defer func() { err = errors.Join(err, profile.Close()) }()
	trust, err := netguard.LoadTrust(outCfg.ExtraCACerts)
	if err != nil {
		return fmt.Errorf("outbound trust: %w", err)
	}
	outbound, err := netguard.New(outCfg, trust, log, netguard.Options{})
	if err != nil {
		return fmt.Errorf("outbound: %w", err)
	}
	directory, err := identity.NewDirectory(identityCfg, log)
	if err != nil {
		return fmt.Errorf("identity directory: %w", err)
	}
	mailer, err := identity.NewMailer(identityCfg, &net.Dialer{})
	if err != nil {
		return fmt.Errorf("transactional mail: %w", err)
	}
	dur, err := durable.OpenLazy(config.New(b.lookup), log)
	if err != nil {
		return fmt.Errorf("temporal: %w", err)
	}
	defer dur.Close()
	extDeps := ext.Deps{Logger: log, Config: config.New(b.lookup), DB: profile.DB}
	exts, err := b.resolveExtensions(ctx, extDeps, spend)
	if err != nil {
		return err
	}
	defer func() { err = errors.Join(err, exts.Close()) }()
	telemetry, err := newRunTelemetry()
	if err != nil {
		return fmt.Errorf("run telemetry: %w", err)
	}

	consumer := name
	settings := streamsservice.DefaultSettings()
	settings.Partitions = pcfg.Events.Partitions
	busOpts := kevents.BusOptions{Retention: kevents.BusRetention, Consumer: consumer}
	if p.events {
		busOpts.Consumer, busOpts.MaxDelivery = "events-"+pollCfg.WorkerID, settings.MaxAttempts
	}
	bus, err := kevents.NewBus(profile.Broker, log, busOpts)
	if err != nil {
		return fmt.Errorf("stream event bus: %w", err)
	}
	ns := pcfg.Events.Namespace
	streamDedup, err := events.NewDedup(profile.Redis, ns, "stream-event", streamEventDedupTTL)
	if err != nil {
		return fmt.Errorf("stream event dedup: %w", err)
	}
	senderNotices, err := events.NewDedup(profile.Redis, ns, streamsservice.NoticePrefix, streamsservice.NoticeInterval)
	if err != nil {
		return fmt.Errorf("sender notice cache: %w", err)
	}
	writeQuota, err := quota.New(profile.Redis, ns)
	if err != nil {
		return fmt.Errorf("event write quota: %w", err)
	}

	d := coreDeps{
		DB: profile.DB, Graph: profile.Graph, APIURL: cfg.Edge.APIURL, AppURL: cfg.AppURL, Log: log, Lookup: b.lookup,
		Broker: profile.Broker, Redis: profile.Redis, Blob: profile.Blob, Secrets: profile.Secrets,
		Durable: dur, Extensions: exts, Directory: directory, Mailer: mailer, Counter: &analytics.Handle{}, Sandbox: sandboxCfg, Outbound: outbound, Agents: agentsCfg, Insights: insightsCfg,
		LiveTurns: profile.LiveTurns, TurnTokens: profile.TurnTokens, RunSettings: runSettings, Telemetry: telemetry,
		Streams: streamsPlumbing{Bus: bus, Dedup: streamDedup, Notices: senderNotices, Quota: writeQuota, Settings: settings, WebhookURL: webhookURL, Consume: p.events},
	}
	g := lifecycle.NewGroup(lifecycle.Options{StartupTimeout: common.StartupTimeout, ShutdownTimeout: common.ShutdownTimeout})
	if health != nil {
		g.Add(health.listener(healthAddr, log))
	}
	if callsTools {
		var sampler ext.RuntimeSampler
		if d.MCPRuntime, sampler, err = newMCPRuntime(ctx, mcpCfg, mcpDeps{DB: profile.DB, Secrets: profile.Secrets, Outbound: outbound, Hooks: exts.WorkloadHooks, Log: log}); err != nil {
			return fmt.Errorf("mcp runtime: %w", err)
		}
		if err := attachWorkloads(ctx, exts.WorkloadHooks, ext.Workloads{Redis: profile.Redis, Backend: mcpCfg.Runtime.Backend, Runtime: sampler}); err != nil {
			return err
		}
	}
	e := newEdge(profile.Gate, authz.Admins{})
	m := buildModules(e, d)

	var missing []string
	if p.worker {
		missing = append(missing, m.runs.Missing()...)
	}
	if p.events {
		missing = append(missing, eventsMissing(m.streamsDeps)...)
	}
	if len(missing) > 0 {
		return fmt.Errorf("%s: no implementation yet for %s", name, strings.Join(missing, ", "))
	}
	if p.job != nil {
		return p.job(ctx, m)
	}
	if p.operator {
		if err := addOperator(g, m, outbound, log); err != nil {
			return err
		}
	}
	if p.reconcile != nil {
		res, err := m.catalog.Reconcile().Reconcile(ctx, *p.reconcile)
		if err != nil {
			return err
		}
		return reportReconcile(b.stdout, len(p.reconcile.Manifest), res, p.reconcile.WorkspaceRegistries)
	}
	if p.serve || p.worker {
		g.Add(m.insights.AnalyticsSender())
	}
	if p.serve {
		modules := append(m.http(), b.extensionModules(ctx, extDeps, e.extension())...)
		srv, err := serve.New(cfg, serve.Options{Version: buildVersion(), Checks: profile.Checks(), OpenAPI: openapi.Spec()}, log, append(modules, slashRedirect())...)
		if err != nil {
			return err
		}
		g.Add(srv)
		if common.OTelEnabled {
			g.Add(brokerHealth(profile, pcfg.Events.Partitions, log))
		}
	}
	if callsTools {
		g.Add(m.connections.DispatchStamps())
	}
	if p.worker {
		if err := b.addWorker(ctx, g, dur, m, exts, spend, health, log); err != nil {
			return err
		}
		g.Add(m.connections.Monitor())
		g.Add(m.insights.InstallationPulse())
	}
	if p.events {
		if err := addEvents(g, profile, pcfg, pollCfg, replyCfg, m, bus, log); err != nil {
			return err
		}
		if err := b.addPartitions(g, profile, log); err != nil {
			return err
		}
	}
	if p.serve && p.worker && p.events {
		g.Add(&runComponent{name: "mcp-reaper", run: d.MCPRuntime.Run, log: log})
		for i, h := range exts.WorkloadHooks {
			if h.Run != nil {
				g.Add(&runComponent{name: fmt.Sprintf("workload hooks %d", i+1), run: h.Run, close: h.Close, log: log})
			}
		}
	}
	if health != nil {
		g.Add(health.ready())
	}
	return g.Run(ctx)
}

// addWorker registers runs on the agent and trigger queues, keeps its
// schedules, and adds both workers.
func (b *Build) addWorker(ctx context.Context, g *lifecycle.Group, dur *durable.Durable, m *moduleSet, exts *extensions, spend money.Currency, health *processHealth, log *slog.Logger) error {
	agentW, triggerW := dur.AgentWorker(), dur.TriggerWorker()
	if health != nil {
		health.pollers = map[string]kdurable.Worker{dur.Config.Queues.Agent: agentW, dur.Config.Queues.Trigger: triggerW}
	}
	m.runs.Register(agentW)
	m.runs.RegisterTriggers(triggerW)
	if err := registered(agentW, m.runs.AgentActivities()); err != nil {
		return fmt.Errorf("agent queue %s: %w", dur.Config.Queues.Agent, err)
	}
	if err := registered(triggerW, m.runs.TriggerActivities()); err != nil {
		return fmt.Errorf("trigger queue %s: %w", dur.Config.Queues.Trigger, err)
	}
	schedules := m.runs.Schedules()
	g.Add(lifecycle.Loop("schedules", func(ctx context.Context) error {
		if err := dur.WaitNamespace(ctx); err != nil || ctx.Err() != nil {
			return err
		}
		for _, s := range schedules {
			if err := dur.Scheduler().Ensure(ctx, s); err != nil {
				if ctx.Err() != nil {
					return nil
				}
				return fmt.Errorf("schedule %s: %w", s.ID, err)
			}
		}
		<-ctx.Done()
		return nil
	}))
	log.InfoContext(ctx, "worker configured", slog.String("agent_queue", dur.Config.Queues.Agent),
		slog.String("trigger_queue", dur.Config.Queues.Trigger), slog.Any("limits", dur.Config.Limits),
		slog.String("billing_currency", string(exts.CustomerPricing.Currency())), slog.String("spend_currency", string(spend)))
	g.Add(durable.Worker("agent worker", dur, agentW))
	g.Add(durable.Worker("trigger worker", dur, triggerW))
	g.Add(m.runs.Settlement())
	return nil
}

// addEvents adds streams' consumers, the pollers, external delivery, the
// task-event groups (replies, platform stream, trigger outcomes) and the outbox
// relay with identity's membership-removal handler.
func addEvents(g *lifecycle.Group, profile *cluster.Profile, pcfg cluster.Config, pollCfg polling.Config, replyCfg replies.Config, m *moduleSet, bus *kevents.Bus, log *slog.Logger) error {
	ns := pcfg.Events.Namespace
	deliveryDedup, err := events.NewDedup(profile.Redis, ns, delivery.DedupPrefix(), kevents.BusRetention)
	if err != nil {
		return err
	}
	pollers, err := m.streams.Pollers(streams.PollerDeps{
		Config: pollCfg, Redis: profile.Redis, Instances: m.connections.Lookup(), GatewaySecret: pcfg.Authn.GatewaySecret,
	})
	if err != nil {
		return err
	}
	members := m.identity.Members()
	deliveries, err := m.streams.Delivery(streams.DeliveryDeps{
		Dedup: deliveryDedup, Consumer: "external-" + pollCfg.WorkerID,
		Slugs: func(ctx context.Context, owner, workspaceID string) (string, error) {
			ws, err := members.ListWorkspaces(ctx, authn.Principal{UserID: owner})
			if err != nil {
				return "", err
			}
			for _, w := range ws {
				if w.ID == workspaceID {
					return w.Slug, nil
				}
			}
			return "", fmt.Errorf("workspace %s is not one of user %s's", workspaceID, owner)
		},
	})
	if err != nil {
		return err
	}
	replyDedup, err := events.NewDedup(profile.Redis, ns, replies.DedupPrefix, replyCfg.DedupTTL)
	if err != nil {
		return err
	}
	taskReplies, err := m.streams.Replies(streams.ReplyDeps{
		Redis: profile.Redis, Dedup: replyDedup, Consumer: "delivery-" + pollCfg.WorkerID, Config: replyCfg,
	})
	if err != nil {
		return err
	}
	name, onRemoval := m.identity.MembershipRemovalHandler()
	relay := kevents.NewRelay(profile.DB, bus, log, kevents.RelayOptions{Handlers: map[string]kevents.OutboxHandler{name: onRemoval}})
	g.Add(lifecycle.Loop("outbox relay", relay.Run))
	for _, c := range m.streams.Consumers() {
		g.Add(c)
	}
	for _, c := range pollers {
		g.Add(c)
	}
	for _, c := range deliveries {
		g.Add(c)
	}
	for _, c := range append(m.streams.TaskEventConsumers(), taskReplies...) {
		g.Add(c)
	}
	log.Info("events configured", "worker_id", pollCfg.WorkerID, "poll_interval", pollCfg.Interval,
		"max_pollers", pollCfg.MaxPollers, "relay_handlers", []string{name})
	return nil
}
