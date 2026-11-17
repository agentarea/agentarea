package domain

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/api"
)

// A stream served as MCP Events (SEP-3415 @ 2ec39b9c, mcp_events.py): poll and webhook delivery.
const (
	EventsDefaultTTL         = time.Hour
	EventsMinTTL             = time.Minute
	EventsMaxTTL             = 24 * time.Hour
	EventsDefaultMaxEvents   = 50
	EventsMaxEvents          = 500
	EventsNextPollMs         = 10_000
	MaxExternalSubscriptions = 100
	pollCursorVersion        = "v1"
)

// EventDeliveryModes are the delivery modes every event type offers.
func EventDeliveryModes() []string { return []string{"poll", "webhook"} }

func eventsError(code int, message string, data map[string]any) *api.EventsError {
	return &api.EventsError{Code: code, Message: message, Data: data}
}

// EventArguments is what a subscriber narrows a stream to; every field optional.
type EventArguments struct {
	Kind       *string
	SourceType *string
	SessionKey *string
}

// ParseEventArguments is EventArguments.model_validate (extra="forbid") of decoded JSON; nil is
// no narrowing.
func ParseEventArguments(raw any) (EventArguments, error) {
	var a EventArguments
	if raw == nil {
		return a, nil
	}
	refused := eventsError(api.EventsInvalidParams, "arguments do not match the event's inputSchema", nil)
	m, ok := raw.(map[string]any)
	if !ok {
		return a, refused
	}
	limits := map[string]int{"kind": 255, "source_type": 64, "session_key": 512}
	for k, v := range m {
		limit, known := limits[k]
		if !known {
			return a, refused
		}
		if v == nil {
			continue
		}
		s, ok := v.(string)
		if n := utf8.RuneCountInString(s); !ok || n < 1 || n > limit {
			return a, refused
		}
		switch k {
		case "kind":
			a.Kind = &s
		case "source_type":
			a.SourceType = &s
		default:
			a.SessionKey = &s
		}
	}
	return a, nil
}

// Filter is to_filter: the ExternalFilter a subscriber with these arguments receives through.
func (a EventArguments) Filter() EventFilter {
	f := EventFilter{Kinds: []string{}, Fields: map[string]any{}, SourceType: a.SourceType, SessionKey: a.SessionKey}
	if a.Kind != nil {
		f.Kinds = []string{*a.Kind}
	}
	return f
}

// Canonical is the arguments as compact JSON with sorted keys and no nulls (ensure_ascii).
func (a EventArguments) Canonical() string {
	var parts []string
	for _, kv := range []struct {
		k string
		v *string
	}{{"kind", a.Kind}, {"session_key", a.SessionKey}, {"source_type", a.SourceType}} {
		if kv.v != nil {
			parts = append(parts, PyJSONString(kv.k)+":"+PyJSONString(*kv.v))
		}
	}
	return "{" + strings.Join(parts, ",") + "}"
}

// ParseEventName is parse_event_name: the workspace reference and canonical stream id an event
// type name ("<workspace>/<stream id>") holds.
func ParseEventName(name string) (workspace, streamID string, err error) {
	workspace, stream, _ := strings.Cut(name, "/")
	id, ok := canonicalUUID(stream)
	if workspace == "" || !ok {
		return "", "", eventsError(api.EventsNotFound, "no event type "+PyRepr(name), map[string]any{"kind": "event"})
	}
	return workspace, id, nil
}

// canonicalUUID is str(UUID(s)).
func canonicalUUID(s string) (string, bool) {
	s = strings.ReplaceAll(strings.ReplaceAll(s, "urn:", ""), "uuid:", "")
	s = strings.ReplaceAll(strings.Trim(s, "{}"), "-", "")
	if len(s) != 32 {
		return "", false
	}
	if _, err := hex.DecodeString(s); err != nil {
		return "", false
	}
	s = strings.ToLower(s)
	return s[:8] + "-" + s[8:12] + "-" + s[12:16] + "-" + s[16:20] + "-" + s[20:], true
}

// PollCursor is a poll position: the last event seen in the read model, and when the poll was answered.
type PollCursor struct {
	At       time.Time
	Sequence int64
}

// Encode is "v1:<at ms>:<sequence>", URL-safe base64 without padding.
func (c PollCursor) Encode() string {
	raw := pollCursorVersion + ":" + strconv.FormatInt(c.At.UnixMilli(), 10) + ":" + strconv.FormatInt(c.Sequence, 10)
	return base64.RawURLEncoding.EncodeToString([]byte(raw))
}

// DecodePollCursor reads a cursor Encode wrote; anything else is invalid params.
func DecodePollCursor(text string) (PollCursor, error) {
	refused := eventsError(api.EventsInvalidParams, "cursor is not one this server issued", nil)
	raw, err := base64.URLEncoding.DecodeString(text + strings.Repeat("=", (4-len(text)%4)%4))
	if err != nil || !utf8.Valid(raw) {
		return PollCursor{}, refused
	}
	parts := strings.Split(string(raw), ":")
	if len(parts) != 3 || parts[0] != pollCursorVersion {
		return PollCursor{}, refused
	}
	ms, err := strconv.ParseInt(parts[1], 10, 64)
	if err != nil {
		return PollCursor{}, refused
	}
	seq, err := strconv.ParseInt(parts[2], 10, 64)
	if err != nil {
		return PollCursor{}, refused
	}
	return PollCursor{At: time.UnixMilli(ms).UTC(), Sequence: seq}, nil
}

// Before is whether events after this position may have left the read model by windowStart.
func (c PollCursor) Before(windowStart time.Time) bool { return c.At.Before(windowStart) }

// ValidateWebhookSecret refuses what is not a Standard Webhooks secret: whsec_ and the base64 of
// 24 to 64 bytes.
func ValidateWebhookSecret(secret string) error {
	encoded, ok := strings.CutPrefix(secret, "whsec_")
	if !ok {
		return eventsError(api.EventsInvalidParams, "delivery.secret must start with whsec_", nil)
	}
	key, err := base64.StdEncoding.DecodeString(encoded)
	if err != nil || strings.ContainsAny(encoded, "\r\n") {
		return eventsError(api.EventsInvalidParams, "delivery.secret is not base64", nil)
	}
	if len(key) < 24 || len(key) > 64 {
		return eventsError(api.EventsInvalidParams, "delivery.secret must encode 24 to 64 random bytes", nil)
	}
	return nil
}

// SubscriptionKey is subscription_id: the routing handle of the subscription key (principal,
// url, event, arguments).
func SubscriptionKey(subscriber, url, streamID string, a EventArguments) string {
	key := "[" + PyJSONString(subscriber) + "," + PyJSONString(url) + "," + PyJSONString(streamID) + "," + PyJSONString(a.Canonical()) + "]"
	sum := sha256.Sum256([]byte(key))
	return "sub_" + hex.EncodeToString(sum[:])[:32]
}

// GrantRefreshBefore is the expiry granted for a suggested TTL; none is answered with the longest.
func GrantRefreshBefore(ttlMs *int64, now time.Time) time.Time {
	if ttlMs == nil {
		return now.Add(EventsMaxTTL)
	}
	return now.Add(min(max(time.Duration(*ttlMs)*time.Millisecond, EventsMinTTL), EventsMaxTTL))
}

// EventsInputSchema is EventArguments.model_json_schema().
func EventsInputSchema() json.RawMessage {
	return json.RawMessage(`{"additionalProperties":false,"description":"What a subscriber narrows a stream to; every field optional.",` +
		`"properties":{` +
		`"kind":{"anyOf":[{"maxLength":255,"minLength":1,"type":"string"},{"type":"null"}],"default":null,` +
		`"description":"Only events of this kind, or of a kind under it (order matches order.paid).","title":"Kind"},` +
		`"source_type":{"anyOf":[{"maxLength":64,"minLength":1,"type":"string"},{"type":"null"}],"default":null,` +
		`"description":"Only events a source of this catalog entry brought (github, telegram).","title":"Source Type"},` +
		`"session_key":{"anyOf":[{"maxLength":512,"minLength":1,"type":"string"},{"type":"null"}],"default":null,` +
		`"description":"Only events of this session: one chat, one thread.","title":"Session Key"}},` +
		`"title":"EventArguments","type":"object"}`)
}

// EventsPayloadSchema is EventEnvelope.model_json_schema().
func EventsPayloadSchema() json.RawMessage {
	const optionalString = `"anyOf":[{"type":"string"},{"type":"null"}],"default":null`
	return json.RawMessage(`{"$defs":{"EnvelopeAttachment":{"properties":{` +
		`"name":{"title":"Name","type":"string"},` +
		`"mime":{` + optionalString + `,"title":"Mime"},` +
		`"size":{"anyOf":[{"type":"integer"},{"type":"null"}],"default":null,"title":"Size"},` +
		`"sha256":{` + optionalString + `,"title":"Sha256"},` +
		`"ref":{"title":"Ref","type":"string"}},` +
		`"required":["name","ref"],"title":"EnvelopeAttachment","type":"object"}},` +
		`"description":"An event as every subscriber receives it (ADR-0040 §2).","properties":{` +
		`"v":{"description":"Envelope version.","title":"V","type":"integer"},` +
		`"id":{"description":"The event id; a repeat of the event has the same one.","title":"Id","type":"string"},` +
		`"workspace_id":{"title":"Workspace Id","type":"string"},` +
		`"stream_id":{"title":"Stream Id","type":"string"},` +
		`"source_id":{` + optionalString + `,"title":"Source Id"},` +
		`"source_type":{` + optionalString + `,"description":"The source's catalog entry.","title":"Source Type"},` +
		`"kind":{"title":"Kind","type":"string"},` +
		`"key":{"description":"The key the event was deduplicated by.","title":"Key","type":"string"},` +
		`"session_key":{` + optionalString + `,"title":"Session Key"},` +
		`"sender":{` + optionalString + `,"title":"Sender"},` +
		`"received_at":{"format":"date-time","title":"Received At","type":"string"},` +
		`"occurred_at":{"description":"The provider's own time, else when received.","format":"date-time","title":"Occurred At","type":"string"},` +
		`"depth":{"description":"Causation depth; a forward adds one.","title":"Depth","type":"integer"},` +
		`"correlation_id":{` + optionalString + `,"title":"Correlation Id"},` +
		`"causation_id":{` + optionalString + `,"title":"Causation Id"},` +
		`"data":{"additionalProperties":true,"description":"headers (credentials removed) and body as sent; a body over 64 KiB is body_ref.","title":"Data","type":"object"},` +
		`"attachments":{"items":{"$ref":"#/$defs/EnvelopeAttachment"},"title":"Attachments","type":"array"}},` +
		`"required":["v","id","workspace_id","stream_id","kind","key","received_at","occurred_at","depth","data"],` +
		`"title":"EventEnvelope","type":"object"}`)
}
