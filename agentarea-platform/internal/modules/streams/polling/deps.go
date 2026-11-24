package polling

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"time"

	"go.opentelemetry.io/otel/metric"
	"go.opentelemetry.io/otel/trace"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// Source is one source the pollers act on, with its type's entry.
type Source struct {
	ID             string
	WorkspaceID    string
	CreatedBy      string
	Kind           string
	Slug           string
	WebhookID      string
	CredentialKey  string
	Config         map[string]any
	Cursor         string
	RegisteredURL  string
	SubscriptionID string
	// RefreshBefore nil is a grant with no expiry. While PollError is set, RefreshBefore is
	// when to subscribe again and PolledAt when the failed attempt was made.
	RefreshBefore *time.Time
	PollError     string
	PolledAt      *time.Time
	// MCPInstanceID is the MCP server the config names, set only when that server is one
	// of the source's own workspace.
	MCPInstanceID string
	Entry         Entry
	// EntrySpec is the entry as stored, to tell when it changed.
	EntrySpec string
	// Held is a source that exists but cannot be acted on now: its type has no valid catalog
	// entry, its webhook type registers nothing, or its config cannot be read. It counts as
	// present, so its webhook is not taken back, and nothing else is done with it.
	Held bool
}

// Source kinds the pollers read.
const (
	KindWebhook = "webhook"
	KindPoll    = "poll"
)

// Sources reads the sources of every workspace and records what polling and registration did.
type Sources interface {
	Load(ctx context.Context) ([]Source, error)
	Polled(ctx context.Context, sourceID, cursor string) error
	Failed(ctx context.Context, sourceID, reason string) error
	Registered(ctx context.Context, sourceID, url string) error
	// Unregistered clears the URL a source was registered at, after its webhook was taken back.
	Unregistered(ctx context.Context, sourceID string) error
	SubscribeFailed(ctx context.Context, sourceID, reason string, retryIn time.Duration) error
	Subscribed(ctx context.Context, sourceID, url, subscriptionID string, refreshBefore *time.Time, cursor string) error
}

// Intake runs a polled item, or a gap, through the source's ingest: the same path a webhook
// request takes, so the catalog entry names and keys it and its event id dedups a repeat.
type Intake interface {
	IngestPolled(ctx context.Context, sourceID string, item json.RawMessage, receivedAt time.Time) error
	IngestGap(ctx context.Context, sourceID, reason string, receivedAt time.Time) error
}

// ErrUnprocessable marks an item no retry can ingest: the poll goes on past it, as the
// poll consumer dead-lettered it, instead of holding the cursor on it forever.
var ErrUnprocessable = errors.New("polled item cannot be ingested")

// Credentials reads a source's credentials (channel_cred:<slug>:<key>, secret references resolved).
type Credentials func(ctx context.Context, ws scope.Workspace, userID, slug, credentialKey string) (map[string]string, error)

// RequestCaller sends a templated request to a provider.
type RequestCaller interface {
	Call(ctx context.Context, req Request, v Values) ([]byte, error)
}

// MCPSubscriber subscribes an mcp_events webhook source at its MCP server and takes it back.
type MCPSubscriber interface {
	Subscribe(ctx context.Context, instanceID string, req SubscribeRequest) (SubscribeResult, error)
	Unsubscribe(ctx context.Context, instanceID string, req UnsubscribeRequest) error
}

// Deps are what a Manager runs on.
type Deps struct {
	Sources     Sources
	Credentials Credentials
	Intake      Intake
	Transports  Transports
	Caller      RequestCaller
	MCP         MCPSubscriber
	Claimer     Claimer
	// WebhookURL is the public URL of a webhook id, as the API shows it.
	WebhookURL func(webhookID string) string
	// Interval is how often the set of sources is read again (AGENTAREA_EVENT_POLL_INTERVAL).
	Interval time.Duration
	// MaxPollers caps this replica's pollers (AGENTAREA_EVENT_MAX_POLLERS).
	MaxPollers int
	Now        func() time.Time
	Log        *slog.Logger
	// Meter and Tracer are the OTel instruments and spans of the manager; both are required.
	Meter  metric.Meter
	Tracer trace.Tracer
}
