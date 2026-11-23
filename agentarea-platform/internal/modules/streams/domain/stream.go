package domain

import (
	"errors"
	"fmt"
	"strings"
	"time"
)

// Stream kinds (StreamKind).
const (
	StreamCustom   = "custom"
	StreamPlatform = "platform"
)

// PlatformStreamName is the reserved name of a workspace's platform stream.
const PlatformStreamName = "platform"

// PlatformSourceType is the source type of the platform stream's one source and of its events.
const PlatformSourceType = "platform"

// Source kinds (SourceKind).
const (
	SourceWebhook  = "webhook"
	SourcePoll     = "poll"
	SourcePlatform = "platform"
)

// Subscription kinds (SubscriptionKind).
const (
	SubTrigger   = "trigger"
	SubForward   = "forward"
	SubExternal  = "external"
	SubProcessor = "processor"
)

// Subscription statuses (SubscriptionStatus).
const (
	SubActive = "active"
	SubPaused = "paused"
	SubFailed = "failed"
)

// Verdicts of a reaction (Verdict).
const (
	VerdictReacted = "reacted"
	VerdictSkipped = "skipped"
	VerdictError   = "error"
	VerdictBatched = "batched"
)

// GaveUpReason is the reason of a reaction the router dead-lettered.
const GaveUpReason = "gave up after the broker's delivery limit"

// BeforeStartReason is the reason of an event received before its subscription started.
const BeforeStartReason = "received before the subscription started"

// EnvelopeVersion is the version of the event envelope this code writes (ADR-0040 §2).
const EnvelopeVersion = 1

// Stream is a streams row. SourceTypes are the source types of its sources, first added first;
// only a read of the stream or of the list fills them.
type Stream struct {
	ID          string
	WorkspaceID string
	Name        string
	Description string
	Kind        string
	CreatedBy   string
	CreatedAt   time.Time
	SourceTypes []string
}

// Senders is who may write to a source of a type that admits senders ({allow, ids, by}).
type Senders struct {
	Allow string   `json:"allow"`
	IDs   []string `json:"ids"`
	By    *string  `json:"by,omitempty"`
}

// Source is a stream_sources row.
type Source struct {
	ID             string
	WorkspaceID    string
	StreamID       string
	Kind           string
	WebhookID      *string
	SourceType     *string
	WebhookConfig  map[string]any
	CredentialKey  *string
	EventTemplates map[string]any
	PollCursor     *string
	PolledAt       *time.Time
	PollError      *string
	RegisteredURL  *string
	SubscriptionID *string
	RefreshBefore  *time.Time
	Senders        map[string]any
	CreatedBy      string
	CreatedAt      time.Time
}

// Subscription is a stream_subscriptions row.
type Subscription struct {
	ID              string
	WorkspaceID     string
	StreamID        string
	Kind            string
	TriggerID       *string
	Filter          map[string]any
	OutputStreamIDs []string
	Status          string
	StartedAt       time.Time
	ExternalID      *string
	Subscriber      *string
	CallbackURL     *string
	SecretName      *string
	ExpiresAt       *time.Time
	VerifiedAt      *time.Time
	LastDeliveryAt  *time.Time
	LastError       *string
	FailedSince     *time.Time
	Code            *string
	CreatedBy       string
	CreatedAt       time.Time
}

// Attachment is a file of an event: Ref is a workspace file path, or the provider's reference.
type Attachment struct {
	Name   string  `json:"name"`
	Mime   *string `json:"mime"`
	Size   *int64  `json:"size"`
	SHA256 *string `json:"sha256"`
	Ref    string  `json:"ref"`
	Stored bool    `json:"stored"`
}

// Event is a stream event as the bus carries it and the events read model holds it.
type Event struct {
	ID            string
	Kind          string
	Source        string
	Subject       *string
	OccurredAt    time.Time
	CorrelationID *string
	CausationID   *string
	Data          map[string]any
	StreamID      string
	WorkspaceID   string
	CreatedBy     string
	EventKey      string
	ReceivedAt    time.Time
	Depth         int
	SourceID      *string
	SourceType    *string
	SessionKey    *string
	Sender        *string
	Attachments   []Attachment
}

// RecordedEvent is an event of the read model with its position and routing tally.
type RecordedEvent struct {
	Event
	Sequence    int64
	RoutedAt    *time.Time
	Subscribers *int
	Reacted     int
	Skipped     int
	Errors      int
}

// Reaction is a trigger_executions row read as a subscription's reaction to an event.
type Reaction struct {
	ID              string
	TriggerID       *string
	SubscriptionID  *string
	StreamID        *string
	EventID         *string
	Status          string
	Verdict         *string
	Reason          *string
	Score           *float64
	TaskID          *string
	DerivedEventIDs []string
	CreatedAt       time.Time
}

// VerdictOf is verdict_of_status: the verdict a reaction row without one implies.
func VerdictOf(status string) string {
	switch status {
	case "success":
		return VerdictReacted
	case "skipped":
		return VerdictSkipped
	case "batched":
		return VerdictBatched
	default:
		return VerdictError
	}
}

// ReactionVerdict is the row's verdict, or the one its status implies.
func (r Reaction) ReactionVerdict() string {
	if r.Verdict != nil && *r.Verdict != "" {
		return *r.Verdict
	}
	return VerdictOf(r.Status)
}

// Processing statuses (ProcessingStatus).
const (
	ProcQueued     = "queued"
	ProcProcessing = "processing"
	ProcHandled    = "handled"
	ProcError      = "error"
	ProcNoHandlers = "no_handlers"
	ProcSkipped    = "skipped"
)

// ProcessingStatuses lists every processing status.
func ProcessingStatuses() []string {
	return []string{ProcQueued, ProcProcessing, ProcHandled, ProcError, ProcNoHandlers, ProcSkipped}
}

// ProcessingStatus is processing_status: what the platform did with an event so far.
func (e RecordedEvent) ProcessingStatus() string {
	if e.RoutedAt == nil {
		return ProcQueued
	}
	subs := 0
	if e.Subscribers != nil {
		subs = *e.Subscribers
	}
	expected := max(subs, e.Reacted)
	switch {
	case expected == 0:
		return ProcNoHandlers
	case e.Errors > 0:
		return ProcError
	case e.Reacted < expected:
		return ProcProcessing
	case e.Skipped == e.Reacted:
		return ProcSkipped
	default:
		return ProcHandled
	}
}

// FeedFilter is the workspace feed's filter.
type FeedFilter struct {
	StreamID   *string
	SourceType *string
	Kind       *string
	Sender     *string
	SessionKey *string
	Result     *string
	Since      *time.Time
	Until      *time.Time
	EventID    *string
	Platform   bool
}

// KindPrefix is "order." for kind "order.*"; empty for an exact kind or none.
func (f FeedFilter) KindPrefix() string {
	if f.Kind == nil || !strings.HasSuffix(*f.Kind, ".*") {
		return ""
	}
	return strings.TrimSuffix(*f.Kind, "*")
}

// ExactKind is the kind when it is not a prefix.
func (f FeedFilter) ExactKind() string {
	if f.Kind == nil || strings.HasSuffix(*f.Kind, ".*") {
		return ""
	}
	return *f.Kind
}

// HasOtherConditions reports a filter the rollup cannot count (anything but stream, source type and platform).
func (f FeedFilter) HasOtherConditions() bool {
	return f.Kind != nil || f.Sender != nil || f.SessionKey != nil || f.Result != nil ||
		f.Since != nil || f.Until != nil || f.EventID != nil
}

// FeedFacets counts the filtered feed per stream and per source type.
type FeedFacets struct {
	Streams     map[string]int64
	SourceTypes map[string]int64
	Capped      bool
}

// FacetCap is how many matching events the facets count under filters the rollup cannot answer.
const FacetCap = 1000

// Stream errors (agentarea_streams/domain/errors.py).
var (
	ErrStreamNotFound       = errors.New("stream not found")
	ErrSourceNotFound       = errors.New("source not found")
	ErrSubscriptionNotFound = errors.New("subscription not found")
	ErrEventNotFound        = errors.New("event not found")
	ErrNameTaken            = errors.New("stream name taken")
	ErrManagedByPlatform    = errors.New("managed by the platform")
	ErrInUse                = errors.New("stream in use")
	ErrNotAForward          = errors.New("not a forward")
	ErrNotAProcessor        = errors.New("not a processor")
	ErrForwardLoop          = errors.New("forward loop")
	ErrProcessorCode        = errors.New("processor code refused")
	ErrProcessorLoop        = errors.New("processor loop")
	ErrQuotaExceeded        = errors.New("quota exceeded")
)

// StreamError is a stream failure whose text is Python's and whose kind is one of the Err values.
type StreamError struct {
	Kind error
	Msg  string
}

func (e *StreamError) Error() string        { return e.Msg }
func (e *StreamError) Is(target error) bool { return target == e.Kind }

// Fail is a StreamError of kind with msg.
func Fail(kind error, msg string) error { return &StreamError{Kind: kind, Msg: msg} }

// StreamNotFound is StreamNotFoundError.
func StreamNotFound(id string) error {
	return Fail(ErrStreamNotFound, fmt.Sprintf("Stream %s not found", id))
}

// SourceNotFound is StreamSourceNotFoundError.
func SourceNotFound(id string) error {
	return Fail(ErrSourceNotFound, fmt.Sprintf("Source %s not found in this stream", id))
}

// SubscriptionNotFound is SubscriptionNotFoundError.
func SubscriptionNotFound(id string) error {
	return Fail(ErrSubscriptionNotFound, fmt.Sprintf("Subscription %s not found in this stream", id))
}

// NameTaken is StreamNameTakenError.
func NameTaken(name string) error {
	return Fail(ErrNameTaken, fmt.Sprintf("A stream named %s already exists in this workspace", PyRepr(name)))
}

// NotAForward is NotAForwardError.
func NotAForward(subID, kind string, triggerID *string) error {
	if triggerID == nil {
		return Fail(ErrNotAForward, fmt.Sprintf("Subscription %s is a %s, not a forward", subID, kind))
	}
	return Fail(ErrNotAForward, fmt.Sprintf("Subscription %s belongs to trigger %s, not a forward; it is removed by deleting the trigger", subID, *triggerID))
}

// NotAProcessor is NotAProcessorError.
func NotAProcessor(subID string) error {
	return Fail(ErrNotAProcessor, fmt.Sprintf("Subscription %s is not a processor", subID))
}

// InUse is StreamInUseError's message.
func InUse(streamID string, triggerIDs []string, forwards, processors [][2]string) error {
	var reasons []string
	if len(triggerIDs) == 1 {
		reasons = append(reasons, fmt.Sprintf("trigger %s subscribes to it; delete the trigger first", triggerIDs[0]))
	} else if len(triggerIDs) > 1 {
		reasons = append(reasons, fmt.Sprintf("triggers %s subscribe to it; delete those triggers first", strings.Join(triggerIDs, ", ")))
	}
	pairs := func(ps [][2]string) string {
		out := make([]string, len(ps))
		for i, p := range ps {
			out[i] = p[0] + " on stream " + p[1]
		}
		return strings.Join(out, ", ")
	}
	if len(forwards) == 1 {
		reasons = append(reasons, fmt.Sprintf("forward %s writes into it; remove that forward from its stream first", pairs(forwards)))
	} else if len(forwards) > 1 {
		reasons = append(reasons, fmt.Sprintf("forwards %s write into it; remove each forward from its stream first", pairs(forwards)))
	}
	if len(processors) == 1 {
		reasons = append(reasons, fmt.Sprintf("processor %s writes into it; delete that processor first (streams_delete_processor)", pairs(processors)))
	} else if len(processors) > 1 {
		reasons = append(reasons, fmt.Sprintf("processors %s write into it; delete each processor first (streams_delete_processor)", pairs(processors)))
	}
	return Fail(ErrInUse, fmt.Sprintf("Stream %s is in use: %s", streamID, strings.Join(reasons, "; ")))
}

// PyRepr is Python's repr() of a str.
func PyRepr(s string) string {
	q := "'"
	if strings.Contains(s, "'") && !strings.Contains(s, `"`) {
		q = `"`
	}
	var b strings.Builder
	b.WriteString(q)
	for _, r := range s {
		switch {
		case r == '\\':
			b.WriteString(`\\`)
		case string(r) == q:
			b.WriteString(`\` + q)
		case r == '\n':
			b.WriteString(`\n`)
		case r == '\r':
			b.WriteString(`\r`)
		case r == '\t':
			b.WriteString(`\t`)
		case r < 0x20 || r == 0x7f:
			fmt.Fprintf(&b, `\x%02x`, r)
		default:
			b.WriteRune(r)
		}
	}
	b.WriteString(q)
	return b.String()
}
