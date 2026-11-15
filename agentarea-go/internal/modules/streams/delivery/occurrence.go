package delivery

import (
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
)

// Envelope is an event as every subscriber receives it (EventEnvelope, ADR-0040 §2).
type Envelope struct {
	V             int                  `json:"v"`
	ID            string               `json:"id"`
	WorkspaceID   string               `json:"workspace_id"`
	StreamID      string               `json:"stream_id"`
	SourceID      *string              `json:"source_id"`
	SourceType    *string              `json:"source_type"`
	Kind          string               `json:"kind"`
	Key           string               `json:"key"`
	SessionKey    *string              `json:"session_key"`
	Sender        *string              `json:"sender"`
	ReceivedAt    time.Time            `json:"received_at"`
	OccurredAt    time.Time            `json:"occurred_at"`
	Depth         int                  `json:"depth"`
	CorrelationID *string              `json:"correlation_id"`
	CausationID   *string              `json:"causation_id"`
	Data          map[string]any       `json:"data"`
	Attachments   []EnvelopeAttachment `json:"attachments"`
}

// EnvelopeAttachment is a file of an envelope.
type EnvelopeAttachment struct {
	Name   string  `json:"name"`
	Mime   *string `json:"mime"`
	Size   *int64  `json:"size"`
	SHA256 *string `json:"sha256"`
	Ref    string  `json:"ref"`
}

// EnvelopeOf is EventEnvelope.of.
func EnvelopeOf(e domain.Event) Envelope {
	atts := make([]EnvelopeAttachment, 0, len(e.Attachments))
	for _, a := range e.Attachments {
		atts = append(atts, EnvelopeAttachment{Name: a.Name, Mime: a.Mime, Size: a.Size, SHA256: a.SHA256, Ref: a.Ref})
	}
	data := e.Data
	if data == nil {
		data = map[string]any{}
	}
	return Envelope{
		V: domain.EnvelopeVersion, ID: e.ID, WorkspaceID: e.WorkspaceID, StreamID: e.StreamID,
		SourceID: e.SourceID, SourceType: e.SourceType, Kind: e.Kind, Key: e.EventKey,
		SessionKey: e.SessionKey, Sender: e.Sender, ReceivedAt: e.ReceivedAt.UTC(), OccurredAt: e.OccurredAt.UTC(),
		Depth: e.Depth, CorrelationID: e.CorrelationID, CausationID: e.CausationID, Data: data, Attachments: atts,
	}
}

// Occurrence is the EventOccurrence a webhook delivers: the event under its type name, with no
// cursor (a push has no poll position).
type Occurrence struct {
	EventID   string   `json:"eventId"`
	Name      string   `json:"name"`
	Timestamp string   `json:"timestamp"`
	Data      Envelope `json:"data"`
	Cursor    *string  `json:"cursor"`
}

// OccurrenceOf is occurrence(event, name) with "cursor": null.
func OccurrenceOf(e domain.Event, name string) Occurrence {
	return Occurrence{EventID: e.ID, Name: name, Timestamp: events.PyISO(e.OccurredAt), Data: EnvelopeOf(e)}
}

// EventName is a stream's event type name, the same on every mount: <workspace slug>/<stream id>.
func EventName(workspaceSlug, streamID string) string { return workspaceSlug + "/" + streamID }

// Terminated is the control message a subscriber that lost read access is sent before removal.
func Terminated() map[string]any {
	return map[string]any{
		"type":  "terminated",
		"error": map[string]any{"code": -32024, "message": "Forbidden", "data": map[string]any{"reason": "Access revoked"}},
	}
}
