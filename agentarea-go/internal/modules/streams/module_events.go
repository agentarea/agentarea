package streams

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"time"

	"github.com/redis/go-redis/v9"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/lifecycle"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/delivery"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/polling"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/service"
)

// PollerDeps are what the pollers need beyond the module's own deps.
type PollerDeps struct {
	Config polling.Config
	// Redis holds the per-source claims.
	Redis *redis.Client
	// Instances answers whether an MCP server is one of a workspace's (connections' Lookup).
	Instances polling.MCPInstances
	// GatewaySecret authenticates the MCP Events calls at the MCP manager (AGENTAREA_MCP_GATEWAY_SECRET).
	GatewaySecret string
}

// Pollers is the event service folded into streams: one poller per poll source, webhook
// registrations kept, every polled item through the source's ingest; and the drain of what the
// event service left on streams.ingest.
func (m *Module) Pollers(p PollerDeps) ([]lifecycle.Component, error) {
	switch {
	case m.d.SourceTypes == nil, m.d.Secrets == nil, m.d.Out == nil, m.d.Bus == nil, m.d.Dedup == nil:
		return nil, errors.New("pollers need the catalog's source types, secrets, outbound clients, the bus and dedup")
	case p.Redis == nil, p.Instances == nil, m.d.Broker == nil:
		return nil, errors.New("pollers need redis, the broker and connections' MCP instances")
	case p.GatewaySecret == "":
		return nil, errors.New("pollers need AGENTAREA_MCP_GATEWAY_SECRET for MCP Events sources")
	}
	log := m.log().With("component", "pollers")
	mgr := polling.NewManager(m.pollingDeps(p, log))
	backlog := polling.Backlog{
		Broker: m.d.Broker, Intake: intake{m.svc}, Consumer: "ingest-" + p.Config.WorkerID,
		Block: 5 * time.Second, Batch: 10, Log: log,
	}
	return []lifecycle.Component{lifecycle.Loop("pollers", mgr.Run), lifecycle.Loop("polled item backlog", backlog.Run)}, nil
}

// pollingDeps is the poll manager over the module: the source's own ingest, the catalog's
// entries, and the API's public webhook URL (TELEGRAM_WEBHOOK_URL over AGENTAREA_API_URL), so a
// provider is registered at the URL the API shows for the source.
func (m *Module) pollingDeps(p PollerDeps, log *slog.Logger) polling.Deps {
	mcp := polling.NewMCPClient(p.Config.ManagerURL, p.GatewaySecret, m.d.Out.Transport(netguard.Internal))
	caller := polling.NewCaller(m.d.Out)
	return polling.Deps{
		Sources: polling.StoredSources{
			DB: m.d.DB, Entries: polling.CatalogEntries(m.d.SourceTypes, log), Instances: p.Instances, Now: m.d.Now, Log: log,
		},
		Credentials: m.svc.SourceCredentials,
		Intake:      intake{m.svc},
		Transports:  polling.NewTransports(caller, m.d.Out.Dialer().DialContext, mcp),
		Caller:      caller,
		MCP:         mcp,
		Claimer:     polling.NewRedisClaimer(p.Redis, p.Config.WorkerID),
		WebhookURL:  m.svc.PublicWebhookURL,
		Interval:    p.Config.Interval,
		MaxPollers:  p.Config.MaxPollers,
		Now:         m.d.Now,
		Log:         log,
	}
}

func (m *Module) log() *slog.Logger {
	if m.d.Log == nil {
		return slog.Default()
	}
	return m.d.Log
}

// intake is the service's polled-item ingest as the pollers see it: an item no retry can ingest
// is polling.ErrUnprocessable.
type intake struct{ svc *service.Service }

func (i intake) IngestPolled(ctx context.Context, sourceID string, item json.RawMessage, receivedAt time.Time) error {
	return unprocessable(i.svc.IngestPolled(ctx, sourceID, item, receivedAt))
}

func (i intake) IngestGap(ctx context.Context, sourceID, reason string, receivedAt time.Time) error {
	return unprocessable(i.svc.IngestGap(ctx, sourceID, reason, receivedAt))
}

func unprocessable(err error) error {
	if errors.Is(err, service.ErrMalformedItem) || errors.Is(err, events.ErrUnprocessable) {
		return fmt.Errorf("%w: %w", polling.ErrUnprocessable, err)
	}
	return err
}

// DeliveryDeps are what external delivery needs beyond the module's own deps.
type DeliveryDeps struct {
	// Dedup is the dedup cache of sent deliveries (prefix delivery.DedupPrefix()).
	Dedup events.Dedup
	// Slugs names a workspace's slug, for the event type name (identity's workspaces).
	Slugs delivery.Slugs
	// Consumer names this replica in the Delivery group.
	Consumer string
}

// Delivery is the external subscribers' webhook delivery: one consumer per delivery topic and
// the expired-subscriber sweeper.
func (m *Module) Delivery(p DeliveryDeps) ([]lifecycle.Component, error) {
	if m.d.Broker == nil || m.d.Graph == nil || m.d.Secrets == nil || m.d.Out == nil {
		return nil, errors.New("external delivery needs the broker, the graph, secrets and outbound clients")
	}
	now := m.d.Now
	if now == nil {
		now = time.Now
	}
	log := m.log().With("component", "external delivery")
	x, err := delivery.New(delivery.Deps{
		Broker: m.d.Broker, Dedup: p.Dedup, Readers: m.d.Graph,
		Subscriptions: delivery.Stored{DB: m.d.DB, Secrets: m.d.Secrets},
		Endpoint:      delivery.NewEndpoint(m.d.Out, now, log),
		Slugs:         p.Slugs, Consumer: p.Consumer, Now: now, Log: log,
	})
	if err != nil {
		return nil, err
	}
	return x.Components(), nil
}
