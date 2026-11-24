// Package router is the stream consumers of the worker: the events view, the router and its
// subscription handlers (trigger, forward, processor, external), and the subscription cache
// that follows streams.subscriptions.changed.
package router

import (
	"encoding/json"
	"fmt"
	"strconv"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
)

func streamAttributes() []string {
	return []string{"streamid", "workspaceid", "createdby", "eventkey", "receivedat", "depth"}
}

// EventFromBus is StreamEvent.from_bus through consumed_stream_event: a message carrying no stream
// event is events.ErrUnprocessable, dead-lettered at once.
func EventFromBus(m events.IntegrationEvent) (domain.Event, error) {
	e, err := fromBus(m)
	if err != nil {
		return e, fmt.Errorf("%w: not a stream event: %w", events.ErrUnprocessable, err)
	}
	return e, nil
}

func fromBus(m events.IntegrationEvent) (domain.Event, error) {
	x := m.Extensions
	var missing []string
	for _, n := range streamAttributes() {
		if _, ok := x[n]; !ok {
			missing = append(missing, n)
		}
	}
	if len(missing) > 0 {
		return domain.Event{}, fmt.Errorf("event %s is not a stream event: no %v", m.ID, missing)
	}
	stream, err := uuid.Parse(x["streamid"])
	if err != nil {
		return domain.Event{}, fmt.Errorf("streamid: %w", err)
	}
	received, err := events.ParsePyISO(x["receivedat"])
	if err != nil {
		return domain.Event{}, fmt.Errorf("receivedat: %w", err)
	}
	depth, err := strconv.Atoi(x["depth"])
	if err != nil {
		return domain.Event{}, fmt.Errorf("depth: %w", err)
	}
	e := domain.Event{
		ID: m.ID, Kind: m.Type, Source: m.Source, OccurredAt: m.Time, Data: m.Data,
		StreamID: stream.String(), WorkspaceID: x["workspaceid"], CreatedBy: x["createdby"],
		EventKey: x["eventkey"], ReceivedAt: received.UTC(), Depth: depth,
		Subject: opt(m.Subject), CorrelationID: opt(m.CorrelationID), CausationID: opt(m.CausationID),
	}
	if e.Data == nil {
		e.Data = map[string]any{}
	}
	if v, ok := x["sourceid"]; ok {
		u, err := uuid.Parse(v)
		if err != nil {
			return domain.Event{}, fmt.Errorf("sourceid: %w", err)
		}
		s := u.String()
		e.SourceID = &s
	}
	e.SourceType = present(x, "sourcetype")
	e.SessionKey = present(x, "sessionkey")
	e.Sender = present(x, "sender")
	e.Attachments = []domain.Attachment{}
	if raw := x["attachments"]; raw != "" {
		var listed []attachment
		if err := json.Unmarshal([]byte(raw), &listed); err != nil {
			return domain.Event{}, fmt.Errorf("attachments: %w", err)
		}
		for _, a := range listed {
			stored := a.Stored == nil || *a.Stored
			e.Attachments = append(e.Attachments, domain.Attachment{Name: a.Name, Mime: a.Mime, Size: a.Size,
				SHA256: a.SHA256, Ref: a.Ref, Stored: stored})
		}
	}
	return e, nil
}

type attachment struct {
	Name   string  `json:"name"`
	Mime   *string `json:"mime"`
	Size   *int64  `json:"size"`
	SHA256 *string `json:"sha256"`
	Ref    string  `json:"ref"`
	Stored *bool   `json:"stored"`
}

func opt(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

func present(x map[string]string, k string) *string {
	v, ok := x[k]
	if !ok {
		return nil
	}
	return &v
}
