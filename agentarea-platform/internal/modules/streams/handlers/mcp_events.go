package handlers

import (
	"bytes"
	"context"
	"encoding/json"
	"math"
	"strconv"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/delivery"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
)

// MCPEvents is every stream the caller may read served as MCP Events (mcp_events.MCPEvents):
// an event type is a stream, named "<workspace slug>/<stream id>"; poll and webhook delivery.
type MCPEvents struct {
	svc       *service.Service
	callbacks service.Callbacks
	now       func() time.Time
}

var _ api.MCPEvents = (*MCPEvents)(nil)

// NewMCPEvents serves the events extension over svc; callbacks checks and challenges webhook
// subscribers' endpoints.
func NewMCPEvents(svc *service.Service, callbacks service.Callbacks, now func() time.Time) *MCPEvents {
	return &MCPEvents{svc: svc, callbacks: callbacks, now: now}
}

func invalidParams() error {
	return &api.EventsError{Code: api.EventsInvalidParams, Message: "Invalid request parameters"}
}

// Serve implements api.MCPEvents.
func (m *MCPEvents) Serve(ctx context.Context, scope api.EventsScope, method string, raw json.RawMessage) (any, error) {
	p := map[string]any{}
	if trimmed := bytes.TrimSpace(raw); len(trimmed) > 0 && string(trimmed) != "null" {
		dec := json.NewDecoder(bytes.NewReader(trimmed))
		dec.UseNumber()
		if dec.Decode(&p) != nil {
			return nil, invalidParams()
		}
	}
	switch method {
	case "events/list":
		if _, err := optString(p, "cursor"); err != nil {
			return nil, err
		}
		return m.list(ctx, scope)
	case "events/poll":
		return m.poll(ctx, scope, p)
	case "events/subscribe":
		return m.subscribe(ctx, scope, p)
	case "events/unsubscribe":
		return m.unsubscribe(ctx, scope, p)
	}
	return nil, &api.EventsError{Code: -32601, Message: "Method not found"}
}

type eventType struct {
	Name          string          `json:"name"`
	Title         string          `json:"title"`
	Description   string          `json:"description"`
	Delivery      []string        `json:"delivery"`
	InputSchema   json.RawMessage `json:"inputSchema"`
	PayloadSchema json.RawMessage `json:"payloadSchema"`
}

func (m *MCPEvents) list(ctx context.Context, scope api.EventsScope) (any, error) {
	callers, err := scope.Workspaces(ctx)
	if err != nil {
		return nil, err
	}
	out := []eventType{}
	for _, c := range callers {
		streams, err := m.svc.EventStreams(ctx, c)
		if err != nil {
			return nil, err
		}
		for _, st := range streams {
			description := st.Description
			if description == "" {
				description = "Events of the stream " + st.Name
			}
			out = append(out, eventType{
				Name: delivery.EventName(c.Workspace.Slug(), st.ID), Title: st.Name, Description: description,
				Delivery: domain.EventDeliveryModes(), InputSchema: domain.EventsInputSchema(), PayloadSchema: domain.EventsPayloadSchema(),
			})
		}
	}
	return map[string]any{"events": out}, nil
}

// open is MCPEvents._open: the caller in the workspace the name holds, and the stream it reads.
func (m *MCPEvents) open(ctx context.Context, scope api.EventsScope, name string) (authn.Caller, string, error) {
	ws, streamID, err := domain.ParseEventName(name)
	if err != nil {
		return authn.Caller{}, "", err
	}
	c, err := scope.Enter(ctx, ws)
	if err != nil {
		return authn.Caller{}, "", err
	}
	found, readable, err := m.svc.EventStream(ctx, c, streamID)
	switch {
	case err != nil:
		return authn.Caller{}, "", err
	case !found:
		return authn.Caller{}, "", &api.EventsError{Code: api.EventsNotFound, Message: "no event type " + domain.PyRepr(name),
			Data: map[string]any{"kind": "event"}}
	case !readable:
		return authn.Caller{}, "", &api.EventsError{Code: api.EventsForbidden, Message: "you may not read this stream"}
	}
	return c, streamID, nil
}

type polled struct {
	EventID   string            `json:"eventId"`
	Name      string            `json:"name"`
	Timestamp string            `json:"timestamp"`
	Data      delivery.Envelope `json:"data"`
}

type pollResult struct {
	Events     []polled `json:"events"`
	Cursor     string   `json:"cursor"`
	Truncated  bool     `json:"truncated"`
	HasMore    bool     `json:"hasMore"`
	NextPollMs int      `json:"nextPollMs"`
}

func (m *MCPEvents) poll(ctx context.Context, scope api.EventsScope, p map[string]any) (any, error) {
	name, err := reqString(p, "name")
	if err != nil {
		return nil, err
	}
	rawArgs, err := optObject(p, "arguments")
	if err != nil {
		return nil, err
	}
	cursor, err := optString(p, "cursor")
	if err != nil {
		return nil, err
	}
	maxAge, _, err := optInt(p, "maxAgeMs", 0)
	if err != nil {
		return nil, err
	}
	maxEvents, _, err := optInt(p, "maxEvents", 1)
	if err != nil {
		return nil, err
	}
	c, streamID, err := m.open(ctx, scope, name)
	if err != nil {
		return nil, err
	}
	args, err := domain.ParseEventArguments(rawArgs)
	if err != nil {
		return nil, err
	}
	now := m.now().UTC()
	windowStart := now.Add(-m.svc.EventsRetention())
	if cursor == nil {
		head, err := m.svc.EventsHead(ctx, c, streamID)
		if err != nil {
			return nil, err
		}
		return pollResult{Events: []polled{}, Cursor: domain.PollCursor{At: now, Sequence: head}.Encode(), NextPollMs: domain.EventsNextPollMs}, nil
	}
	at, err := domain.DecodePollCursor(*cursor)
	if err != nil {
		return nil, err
	}
	since, truncated := windowStart, at.Before(windowStart)
	if maxAge != nil {
		floor := now.Add(-time.Duration(*maxAge) * time.Millisecond)
		truncated = truncated || at.Before(floor)
		since = maxTime(since, floor)
	}
	limit := domain.EventsDefaultMaxEvents
	if maxEvents != nil {
		limit = int(min(*maxEvents, domain.EventsMaxEvents))
	}
	page, err := m.svc.EventsAfter(ctx, c, streamID, at.Sequence, since, args.Filter(), limit)
	if err != nil {
		return nil, err
	}
	out := pollResult{Events: make([]polled, 0, len(page.Events)), Cursor: domain.PollCursor{At: now, Sequence: page.Position}.Encode(),
		Truncated: truncated, HasMore: page.HasMore, NextPollMs: domain.EventsNextPollMs}
	for _, e := range page.Events {
		out.Events = append(out.Events, polled{EventID: e.ID, Name: name, Timestamp: events.PyISO(e.OccurredAt), Data: delivery.EnvelopeOf(e.Event)})
	}
	return out, nil
}

func maxTime(a, b time.Time) time.Time {
	if a.After(b) {
		return a
	}
	return b
}

// subscriberOf is subscriber_of: the principal a webhook subscription is keyed by.
func subscriberOf(c authn.Caller) string {
	switch {
	case c.Credential != nil && c.Credential.KeyID != "":
		return "key:" + c.Credential.KeyID
	case c.ClientID != "":
		return "client:" + c.ClientID
	}
	return "user:" + c.UserID
}

type deliveryStatus struct {
	Active         bool    `json:"active"`
	LastDeliveryAt *string `json:"lastDeliveryAt"`
	LastError      *string `json:"lastError"`
	FailedSince    *string `json:"failedSince,omitempty"`
}

type subscribeResult struct {
	ID             string          `json:"id"`
	RefreshBefore  string          `json:"refreshBefore"`
	Cursor         *string         `json:"cursor"`
	Truncated      bool            `json:"truncated"`
	DeliveryStatus *deliveryStatus `json:"deliveryStatus,omitempty"`
}

func isoOrNil(t *time.Time) *string {
	if t == nil {
		return nil
	}
	s := events.PyISO(*t)
	return &s
}

func (m *MCPEvents) subscribe(ctx context.Context, scope api.EventsScope, p map[string]any) (any, error) {
	name, err := reqString(p, "name")
	if err != nil {
		return nil, err
	}
	rawArgs, err := optObject(p, "arguments")
	if err != nil {
		return nil, err
	}
	d, err := optObject(p, "delivery")
	if err != nil || d == nil {
		return nil, invalidParams()
	}
	mode, err := optString(d, "mode")
	if err != nil {
		return nil, err
	}
	url, err := reqString(d, "url")
	if err != nil {
		return nil, err
	}
	secret, err := reqString(d, "secret")
	if err != nil {
		return nil, err
	}
	cursor, err := optString(p, "cursor")
	if err != nil {
		return nil, err
	}
	if _, _, err := optInt(p, "maxAgeMs", 0); err != nil {
		return nil, err
	}
	ttl, ttlSet, err := optInt(p, "ttlMs", 0)
	if err != nil {
		return nil, err
	}
	if mode != nil && *mode != "webhook" {
		return nil, &api.EventsError{Code: api.EventsUnsupported, Message: "events/subscribe serves webhook delivery only",
			Data: map[string]any{"feature": "deliveryMode", "value": *mode}}
	}
	c, streamID, err := m.open(ctx, scope, name)
	if err != nil {
		return nil, err
	}
	args, err := domain.ParseEventArguments(rawArgs)
	if err != nil {
		return nil, err
	}
	if !ttlSet {
		v := domain.EventsDefaultTTL.Milliseconds()
		ttl = &v
	}
	made, err := m.svc.SubscribeExternal(ctx, c, m.callbacks, service.ExternalSubscribe{
		StreamID: streamID, Subscriber: subscriberOf(c), URL: url, Secret: secret, Arguments: args, TTLMs: ttl, Now: m.now().UTC(),
	})
	if err != nil {
		return nil, err
	}
	out := subscribeResult{ID: made.ID, RefreshBefore: events.PyISO(made.RefreshBefore), Truncated: cursor != nil}
	if s := made.Existing; s != nil {
		out.DeliveryStatus = &deliveryStatus{Active: s.Status == domain.SubActive, LastDeliveryAt: isoOrNil(s.LastDeliveryAt),
			LastError: s.LastError, FailedSince: isoOrNil(s.FailedSince)}
	}
	return out, nil
}

func (m *MCPEvents) unsubscribe(ctx context.Context, scope api.EventsScope, p map[string]any) (any, error) {
	name, err := reqString(p, "name")
	if err != nil {
		return nil, err
	}
	rawArgs, err := optObject(p, "arguments")
	if err != nil {
		return nil, err
	}
	d, err := optObject(p, "delivery")
	if err != nil || d == nil {
		return nil, invalidParams()
	}
	url, err := reqString(d, "url")
	if err != nil {
		return nil, err
	}
	c, streamID, err := m.open(ctx, scope, name)
	if err != nil {
		return nil, err
	}
	args, err := domain.ParseEventArguments(rawArgs)
	if err != nil {
		return nil, err
	}
	if err := m.svc.UnsubscribeExternal(ctx, c, streamID, subscriberOf(c), url, args); err != nil {
		return nil, err
	}
	return map[string]any{}, nil
}

func reqString(p map[string]any, key string) (string, error) {
	s, ok := p[key].(string)
	if !ok {
		return "", invalidParams()
	}
	return s, nil
}

func optString(p map[string]any, key string) (*string, error) {
	v, ok := p[key]
	if !ok || v == nil {
		return nil, nil
	}
	s, ok := v.(string)
	if !ok {
		return nil, invalidParams()
	}
	return &s, nil
}

func optObject(p map[string]any, key string) (map[string]any, error) {
	v, ok := p[key]
	if !ok || v == nil {
		return nil, nil
	}
	m, ok := v.(map[string]any)
	if !ok {
		return nil, invalidParams()
	}
	return m, nil
}

// optInt is an optional int field of at least least, read as pydantic's lax int: an integral
// number or a numeric string. set is whether the key was sent at all.
func optInt(p map[string]any, key string, least int64) (v *int64, set bool, err error) {
	raw, set := p[key]
	if !set || raw == nil {
		return nil, set, nil
	}
	var n int64
	switch x := raw.(type) {
	case json.Number:
		if n, err = x.Int64(); err != nil {
			f, ferr := x.Float64()
			if ferr != nil || f != math.Trunc(f) || math.Abs(f) > math.MaxInt64 {
				return nil, true, invalidParams()
			}
			n = int64(f)
		}
	case string:
		if n, err = strconv.ParseInt(x, 10, 64); err != nil {
			return nil, true, invalidParams()
		}
	default:
		return nil, true, invalidParams()
	}
	if n < least {
		return nil, true, invalidParams()
	}
	return &n, true, nil
}
