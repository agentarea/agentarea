package api

import (
	"context"
	"errors"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
)

// ErrTriggerNotFound is a trigger id the workspace has no trigger for.
var ErrTriggerNotFound = errors.New("trigger not found")

// TriggerCreate is triggers_create_cron's and triggers_create_stream's arguments
// (TriggerCreate); Type is "cron" or "stream". Session and Batch are the
// documents the tool was given, nil when none.
type TriggerCreate struct {
	Type             string
	Name             string
	Description      string
	AgentID          string
	CronExpression   *string
	Timezone         *string
	StreamID         *string
	EventFilter      map[string]any
	TaskParameters   map[string]any
	TaskDefinitionID *string
	Conditions       map[string]any
	Enabled          bool
	FailureThreshold int
	Session          map[string]any
	Batch            map[string]any
}

// TriggerView is a trigger as the triggers toolset returns it (_trigger_summary).
type TriggerView struct {
	ID               string         `json:"id"`
	Name             string         `json:"name"`
	Description      string         `json:"description"`
	AgentID          string         `json:"agent_id"`
	TaskDefinitionID *string        `json:"task_definition_id"`
	TriggerType      string         `json:"trigger_type"`
	IsActive         bool           `json:"is_active"`
	CronExpression   *string        `json:"cron_expression"`
	Status           string         `json:"status"`
	NeedsNewOwner    bool           `json:"needs_new_owner"`
	StreamID         *string        `json:"stream_id"`
	EventFilter      map[string]any `json:"event_filter"`
	Session          any            `json:"session"`
	Batch            any            `json:"batch"`
	LastEventAt      *time.Time     `json:"last_event_at"`
}

// TriggerExecution is one entry of triggers_get_history.
type TriggerExecution struct {
	ID              string  `json:"id"`
	Status          string  `json:"status"`
	ExecutedAt      *string `json:"executed_at"`
	ExecutionTimeMs int     `json:"execution_time_ms"`
	ErrorMessage    *string `json:"error_message"`
	TaskID          *string `json:"task_id"`
}

// PlatformTriggers is what the platform triggers toolset calls
// (tools/triggers_toolset.py). Delete needs delete on the trigger, Enable and
// Disable edit; each answers false for a trigger that does not exist.
type PlatformTriggers interface {
	List(ctx context.Context, c authn.Caller, agentID string, activeOnly bool, limit int) ([]TriggerView, error)
	// Get returns ErrTriggerNotFound for an unknown id.
	Get(ctx context.Context, c authn.Caller, triggerID string) (TriggerView, error)
	Create(ctx context.Context, c authn.Caller, in TriggerCreate) (TriggerView, error)
	Delete(ctx context.Context, c authn.Caller, triggerID string) (bool, error)
	Enable(ctx context.Context, c authn.Caller, triggerID string) (bool, error)
	Disable(ctx context.Context, c authn.Caller, triggerID string) (bool, error)
	// History is the trigger's executions, newest first.
	History(ctx context.Context, c authn.Caller, triggerID string, limit, offset int) ([]TriggerExecution, error)
}

// EventQuery is streams_list_events' arguments.
type EventQuery struct {
	StreamID   *string
	After      int64
	Before     *int64
	SourceType *string
	Kind       *string
	Sender     *string
	SessionKey *string
	Result     *string
	Since      *time.Time
	Until      *time.Time
	Limit      int
}

// ProcessorChange is streams_update_processor's arguments; nil keeps a field.
type ProcessorChange struct {
	Code        *string
	Outputs     []string
	EventFilter map[string]any
}

// PlatformStreams is what the platform streams toolset calls
// (tools/streams_toolset.py). Each answer is the REST route's response body
// (StreamResponse, SourceTypeResponse, StreamSourceResponse, SourceCreated,
// SubscriptionResponse, StreamEventPage). Every error's text is what the
// toolset reports.
type PlatformStreams interface {
	List(ctx context.Context, c authn.Caller, limit, offset int) (any, error)
	Get(ctx context.Context, c authn.Caller, streamID string) (any, error)
	Create(ctx context.Context, c authn.Caller, name, description string) (any, error)
	Delete(ctx context.Context, c authn.Caller, streamID string) error
	ListSourceTypes(ctx context.Context, c authn.Caller) (any, error)
	ListSources(ctx context.Context, c authn.Caller, streamID string) (any, error)
	// CreateSource takes a SourceCreate document.
	CreateSource(ctx context.Context, c authn.Caller, streamID string, source []byte) (any, error)
	// UpdateSource takes a Senders document.
	UpdateSource(ctx context.Context, c authn.Caller, streamID, sourceID string, senders []byte) (any, error)
	DeleteSource(ctx context.Context, c authn.Caller, streamID, sourceID string) error
	ListSubscriptions(ctx context.Context, c authn.Caller, streamID string) (any, error)
	CreateForward(ctx context.Context, c authn.Caller, streamID string, outputs []string, eventFilter map[string]any) (any, error)
	DeleteForward(ctx context.Context, c authn.Caller, streamID, subscriptionID string) error
	CreateProcessor(ctx context.Context, c authn.Caller, streamID string, outputs []string, code string, eventFilter map[string]any) (any, error)
	UpdateProcessor(ctx context.Context, c authn.Caller, streamID, subscriptionID string, ch ProcessorChange) (any, error)
	DeleteProcessor(ctx context.Context, c authn.Caller, streamID, subscriptionID string) error
	ListEvents(ctx context.Context, c authn.Caller, q EventQuery) (any, error)
}

// StreamRef names the stream stream_events_read_stream read.
type StreamRef struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

// StreamEventItem is one event stream_events_read_stream returns.
type StreamEventItem struct {
	Sequence   int64          `json:"sequence"`
	Kind       string         `json:"kind"`
	Key        string         `json:"key"`
	OccurredAt string         `json:"occurred_at"`
	ReceivedAt string         `json:"received_at"`
	Data       map[string]any `json:"data"`
}

// StreamEventsRead is stream_events_read_stream's output.
type StreamEventsRead struct {
	Stream    StreamRef         `json:"stream"`
	Untrusted string            `json:"untrusted"`
	Events    []StreamEventItem `json:"events"`
	NextAfter int64             `json:"next_after"`
	HasMore   bool              `json:"has_more"`
}

// PlatformStreamEvents is what the platform stream_events toolset calls
// (tools/stream_events_toolset.py).
type PlatformStreamEvents interface {
	// Read is the events of the stream named or identified by stream after
	// sequence after, oldest first; since keeps those received from then on.
	Read(ctx context.Context, c authn.Caller, stream string, after int64, limit int, since *time.Time) (StreamEventsRead, error)
}

// MessageSend is messages_send_message's arguments with its recipient resolved to a member.
type MessageSend struct {
	// UserID is the workspace member the message is for; Recipient is how the answer names them.
	UserID    string
	Recipient string
	// Stream is a stream name or id; "" for the only messenger stream that reaches the member.
	Stream string
	Text   string
}

// MessageSent is messages_send_message's output.
type MessageSent struct {
	Sent      bool      `json:"sent"`
	To        string    `json:"to"`
	Stream    StreamRef `json:"stream"`
	Messenger string    `json:"messenger"`
	MessageID *int64    `json:"message_id"`
	Truncated bool      `json:"truncated"`
}

// PlatformMessages is what the platform messages toolset calls: a message a run starts with a
// member, through the bot of a messenger stream, to the account the member linked.
type PlatformMessages interface {
	Send(ctx context.Context, c authn.Caller, in MessageSend) (MessageSent, error)
}
