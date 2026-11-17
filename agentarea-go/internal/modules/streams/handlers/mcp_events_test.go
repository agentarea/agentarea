package handlers_test

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/delivery"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/handlers"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store/storetest"
)

type eventsScope struct{ c authn.Caller }

func (s eventsScope) Workspaces(context.Context) ([]authn.Caller, error) {
	return []authn.Caller{s.c}, nil
}

func (s eventsScope) Enter(_ context.Context, ws string) (authn.Caller, error) {
	if ws != s.c.Workspace.Slug() && ws != s.c.Workspace.ID() {
		return authn.Caller{}, &api.EventsError{Code: api.EventsNotFound, Message: "no such event type here", Data: map[string]any{"kind": "event"}}
	}
	return s.c, nil
}

type fakeCallbacks struct {
	challenged []string
}

func (f *fakeCallbacks) Check(_ context.Context, url string) error {
	if !strings.HasPrefix(url, "https://") {
		return &api.EventsError{Code: api.EventsInvalidParams, Message: "delivery.url must be https"}
	}
	return nil
}

func (f *fakeCallbacks) Challenge(_ context.Context, url, _, subscription string) error {
	f.challenged = append(f.challenged, url+" "+subscription)
	return nil
}

type eventsRig struct {
	t       *testing.T
	ws      scope.Workspace
	c       authn.Caller
	db      storetest.DB
	graph   *storetest.Graph
	secrets *storetest.Secrets
	cb      *fakeCallbacks
	srv     api.MCPEvents
	now     time.Time
}

func newEventsRig(t *testing.T) *eventsRig {
	t.Helper()
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	g := &eventsRig{t: t, ws: ws, db: storetest.DB{Pool: pool}, graph: &storetest.Graph{AllowAll: true},
		secrets: storetest.NewSecrets(), cb: &fakeCallbacks{}, now: time.Now().UTC().Truncate(time.Millisecond)}
	g.c = authn.Caller{Principal: authn.Principal{UserID: "u1"}, Workspace: ws}
	svc := service.New(service.Deps{DB: g.db, Graph: g.graph, Agents: storetest.Agents{}, Secrets: g.secrets})
	g.srv = handlers.NewMCPEvents(svc, g.cb, func() time.Time { return g.now })
	return g
}

func (g *eventsRig) stream(name string) string {
	g.t.Helper()
	ctx, _ := storetest.Caller(context.Background(), g.ws, "u1")
	svc := service.New(service.Deps{DB: g.db, Graph: g.graph, Agents: storetest.Agents{}})
	st, err := svc.CreateStream(ctx, name, "")
	if err != nil {
		g.t.Fatal(err)
	}
	g.graph.Readable = append(g.graph.Readable, st.ID)
	return st.ID
}

func (g *eventsRig) event(streamID, kind string) domain.Event {
	g.t.Helper()
	now := time.Now().UTC()
	e := domain.Event{ID: uuid.NewString(), Kind: kind, Source: "test", OccurredAt: now, Data: map[string]any{"n": 1}, StreamID: streamID,
		WorkspaceID: g.ws.ID(), CreatedBy: "u1", EventKey: uuid.NewString(), ReceivedAt: now}
	if ok, err := (store.Streams{}).RecordEvent(context.Background(), db.NewSession(g.ws, g.db.Pool), e); err != nil || !ok {
		g.t.Fatalf("record = %v, %v", ok, err)
	}
	return e
}

func (g *eventsRig) serve(method string, params any) (map[string]any, error) {
	g.t.Helper()
	raw, err := json.Marshal(params)
	if err != nil {
		g.t.Fatal(err)
	}
	out, err := g.srv.Serve(context.Background(), eventsScope{g.c}, method, raw)
	if err != nil {
		return nil, err
	}
	body, err := json.Marshal(out)
	if err != nil {
		g.t.Fatal(err)
	}
	var m map[string]any
	if err := json.Unmarshal(body, &m); err != nil {
		g.t.Fatal(err)
	}
	return m, nil
}

func (g *eventsRig) ok(method string, params any) map[string]any {
	g.t.Helper()
	m, err := g.serve(method, params)
	if err != nil {
		g.t.Fatalf("%s: %v", method, err)
	}
	return m
}

// refused asserts the call is refused with code and message, and returns the refusal's data.
func (g *eventsRig) refused(method string, params any, code int, message string) map[string]any {
	g.t.Helper()
	_, err := g.serve(method, params)
	var e *api.EventsError
	if !errors.As(err, &e) || e.Code != code || (message != "" && e.Message != message) {
		g.t.Fatalf("%s %v: err = %v, want %d %q", method, params, err, code, message)
	}
	return e.Data
}

func (g *eventsRig) name(streamID string) string { return g.ws.Slug() + "/" + streamID }

func TestEventsListNamesTheReadableStreams(t *testing.T) {
	g := newEventsRig(t)
	orders := g.stream("orders")
	g.stream("hidden")
	g.graph.Readable = []string{orders}

	got := g.ok("events/list", map[string]any{})
	events, _ := got["events"].([]any)
	if len(events) != 1 {
		t.Fatalf("listed %v", got)
	}
	ev := events[0].(map[string]any)
	delivery, _ := json.Marshal(ev["delivery"])
	if ev["name"] != g.name(orders) || ev["title"] != "orders" || ev["description"] != "Events of the stream orders" ||
		string(delivery) != `["poll","webhook"]` {
		t.Fatalf("event type %v", ev)
	}
	in, _ := ev["inputSchema"].(map[string]any)
	payload, _ := ev["payloadSchema"].(map[string]any)
	if in["title"] != "EventArguments" || payload["title"] != "EventEnvelope" {
		t.Fatalf("schemas %v %v", in, payload)
	}
}

func TestEventsPollPagesFromItsCursor(t *testing.T) {
	g := newEventsRig(t)
	orders := g.stream("orders")
	first := g.ok("events/poll", map[string]any{"name": g.name(orders)})
	if events, _ := first["events"].([]any); len(events) != 0 || first["hasMore"] != false || first["truncated"] != false ||
		first["nextPollMs"] != float64(10000) {
		t.Fatalf("first poll %v", first)
	}
	start, err := domain.DecodePollCursor(first["cursor"].(string))
	if err != nil || start.Sequence != 0 || !start.At.Equal(g.now) {
		t.Fatalf("cursor %+v %v", start, err)
	}

	paid := g.event(orders, "order.paid")
	g.event(orders, "user.joined")
	shipped := g.event(orders, "order.shipped")

	all := g.ok("events/poll", map[string]any{"name": g.name(orders), "cursor": first["cursor"]})
	if events, _ := all["events"].([]any); len(events) != 3 || all["hasMore"] != false {
		t.Fatalf("all %v", all)
	}
	occ := all["events"].([]any)[0].(map[string]any)
	data, _ := occ["data"].(map[string]any)
	if occ["eventId"] != paid.ID || occ["name"] != g.name(orders) || data["kind"] != "order.paid" || data["stream_id"] != orders {
		t.Fatalf("occurrence %v", occ)
	}
	if _, has := occ["cursor"]; has {
		t.Fatalf("a polled occurrence carries no cursor: %v", occ)
	}

	page := g.ok("events/poll", map[string]any{"name": g.name(orders), "cursor": first["cursor"], "arguments": map[string]any{"kind": "order"}, "maxEvents": 1})
	if events, _ := page["events"].([]any); len(events) != 1 || page["hasMore"] != true || events[0].(map[string]any)["eventId"] != paid.ID {
		t.Fatalf("page %v", page)
	}
	next := g.ok("events/poll", map[string]any{"name": g.name(orders), "cursor": page["cursor"], "arguments": map[string]any{"kind": "order"}, "maxEvents": 1})
	if events, _ := next["events"].([]any); len(events) != 1 || next["hasMore"] != false || events[0].(map[string]any)["eventId"] != shipped.ID {
		t.Fatalf("next %v", next)
	}

	head := g.ok("events/poll", map[string]any{"name": g.name(orders)})
	if c, _ := domain.DecodePollCursor(head["cursor"].(string)); c.Sequence == 0 {
		t.Fatalf("head cursor %+v", c)
	}

	old := domain.PollCursor{At: g.now.Add(-8 * 24 * time.Hour)}.Encode()
	stale := g.ok("events/poll", map[string]any{"name": g.name(orders), "cursor": old})
	if events, _ := stale["events"].([]any); stale["truncated"] != true || len(events) != 3 {
		t.Fatalf("stale %v", stale)
	}
	fresh := g.ok("events/poll", map[string]any{"name": g.name(orders), "cursor": first["cursor"], "maxAgeMs": 3600 * 1000})
	if events, _ := fresh["events"].([]any); fresh["truncated"] != false || len(events) != 3 {
		t.Fatalf("fresh %v", fresh)
	}
	g.now = g.now.Add(time.Hour)
	aged := g.ok("events/poll", map[string]any{"name": g.name(orders), "cursor": first["cursor"], "maxAgeMs": 0})
	if events, _ := aged["events"].([]any); aged["truncated"] != true || len(events) != 0 {
		t.Fatalf("aged %v", aged)
	}
}

func TestEventsPollRefusals(t *testing.T) {
	g := newEventsRig(t)
	orders := g.stream("orders")
	missing := uuid.NewString()
	g.refused("events/poll", map[string]any{"name": g.name(missing)}, api.EventsNotFound, "no event type '"+g.name(missing)+"'")
	g.refused("events/poll", map[string]any{"name": "elsewhere/" + orders}, api.EventsNotFound, "no such event type here")
	g.refused("events/poll", map[string]any{"name": g.name(orders), "cursor": "zz"}, api.EventsInvalidParams, "cursor is not one this server issued")
	g.refused("events/poll", map[string]any{"name": g.name(orders), "arguments": map[string]any{"color": "red"}}, api.EventsInvalidParams,
		"arguments do not match the event's inputSchema")
	g.refused("events/poll", map[string]any{}, api.EventsInvalidParams, "Invalid request parameters")
	g.refused("events/poll", map[string]any{"name": g.name(orders), "maxEvents": 0}, api.EventsInvalidParams, "Invalid request parameters")
	g.refused("events/poll", map[string]any{"name": g.name(orders), "maxAgeMs": -1}, api.EventsInvalidParams, "Invalid request parameters")
	g.refused("events/nope", map[string]any{}, -32601, "Method not found")

	g.graph.AllowAll = false
	g.refused("events/poll", map[string]any{"name": g.name(orders)}, api.EventsForbidden, "you may not read this stream")
}

func secret() string {
	return "whsec_" + base64.StdEncoding.EncodeToString([]byte(strings.Repeat("k", 32)))
}

func TestEventsSubscribeCreatesADeliverableSubscriber(t *testing.T) {
	g := newEventsRig(t)
	orders := g.stream("orders")
	url := "https://hook.example/in"
	sub := func(extra map[string]any) map[string]any {
		p := map[string]any{"name": g.name(orders), "delivery": map[string]any{"mode": "webhook", "url": url, "secret": secret()}}
		for k, v := range extra {
			p[k] = v
		}
		return p
	}

	data := g.refused("events/subscribe", map[string]any{"name": g.name(orders), "delivery": map[string]any{"mode": "push", "url": url, "secret": secret()}},
		api.EventsUnsupported, "events/subscribe serves webhook delivery only")
	if data["feature"] != "deliveryMode" || data["value"] != "push" {
		t.Fatalf("data %v", data)
	}
	g.refused("events/subscribe", map[string]any{"name": g.name(orders), "delivery": map[string]any{"url": url, "secret": "nope"}},
		api.EventsInvalidParams, "delivery.secret must start with whsec_")
	g.refused("events/subscribe", map[string]any{"name": g.name(orders), "delivery": map[string]any{"url": "http://hook.example", "secret": secret()}},
		api.EventsInvalidParams, "delivery.url must be https")
	g.refused("events/subscribe", map[string]any{"name": g.name(orders)}, api.EventsInvalidParams, "Invalid request parameters")

	args := map[string]any{"kind": "order"}
	made := g.ok("events/subscribe", sub(map[string]any{"arguments": args}))
	parsed, _ := domain.ParseEventArguments(args)
	id := domain.SubscriptionKey("user:u1", url, orders, parsed)
	if made["id"] != id || made["cursor"] != nil || made["truncated"] != false || made["refreshBefore"] != pyISO(g.now.Add(time.Hour)) {
		t.Fatalf("made %v", made)
	}
	if _, has := made["deliveryStatus"]; has || len(g.cb.challenged) != 1 || g.cb.challenged[0] != url+" "+id {
		t.Fatalf("made %v challenged %v", made, g.cb.challenged)
	}

	subs, err := (store.Streams{}).ExternalOnStream(context.Background(), db.NewSession(g.ws, g.db.Pool), uuid.MustParse(orders))
	if err != nil || len(subs) != 1 {
		t.Fatalf("subscribers %v %v", subs, err)
	}
	row := subs[0]
	if *row.ExternalID != id || *row.Subscriber != "user:u1" || *row.CallbackURL != url || row.CreatedBy != "u1" ||
		*row.SecretName != service.SubscriberSecretName(id) || row.Status != "active" || row.VerifiedAt == nil {
		t.Fatalf("row %+v", row)
	}
	if f := domain.StoredFilter(row.Filter); len(f.Kinds) != 1 || f.Kinds[0] != "order" {
		t.Fatalf("filter %v", row.Filter)
	}
	stored := delivery.Stored{DB: g.db, Secrets: g.secrets}
	active, ok, err := stored.Active(context.Background(), g.ws, row.ID)
	if err != nil || !ok || *active.ExternalID != id {
		t.Fatalf("delivery sees %+v %v %v", active, ok, err)
	}
	if s, ok, err := stored.Secret(context.Background(), g.ws, row.CreatedBy, *row.SecretName); err != nil || !ok || s != secret() {
		t.Fatalf("delivery secret %q %v %v", s, ok, err)
	}

	g.now = g.now.Add(time.Minute)
	again := g.ok("events/subscribe", sub(map[string]any{"arguments": args, "ttlMs": 2 * 3600 * 1000, "cursor": "c"}))
	status, _ := again["deliveryStatus"].(map[string]any)
	if again["id"] != id || again["truncated"] != true || again["refreshBefore"] != pyISO(g.now.Add(2*time.Hour)) ||
		status["active"] != true || status["lastDeliveryAt"] != nil || status["lastError"] != nil || len(g.cb.challenged) != 1 {
		t.Fatalf("refresh %v challenged %v", again, g.cb.challenged)
	}
	if _, has := status["failedSince"]; has {
		t.Fatalf("status %v", status)
	}
	never := g.ok("events/subscribe", sub(map[string]any{"ttlMs": nil}))
	if never["refreshBefore"] != pyISO(g.now.Add(24*time.Hour)) || len(g.cb.challenged) != 1 {
		t.Fatalf("no ttl %v challenged %v", never, g.cb.challenged)
	}

	g.ok("events/unsubscribe", map[string]any{"name": g.name(orders), "arguments": args, "delivery": map[string]any{"url": url}})
	if _, ok, _ := stored.Active(context.Background(), g.ws, row.ID); ok {
		t.Fatal("unsubscribed subscriber is still active")
	}
	if _, ok, _ := stored.Secret(context.Background(), g.ws, "u1", *row.SecretName); ok {
		t.Fatal("unsubscribed subscriber's secret is still stored")
	}
	gone := g.refused("events/unsubscribe", map[string]any{"name": g.name(orders), "arguments": args, "delivery": map[string]any{"url": url}},
		api.EventsNotFound, "no such subscription")
	if gone["kind"] != "subscription" {
		t.Fatalf("data %v", gone)
	}
}

func TestEventsSubscribeStopsAtTheWorkspaceLimit(t *testing.T) {
	g := newEventsRig(t)
	orders := g.stream("orders")
	params := func(n int) map[string]any {
		return map[string]any{"name": g.name(orders), "arguments": map[string]any{"kind": fmt.Sprintf("k%d", n)},
			"delivery": map[string]any{"url": "https://hook.example/in", "secret": secret()}}
	}
	for n := range domain.MaxExternalSubscriptions {
		g.ok("events/subscribe", params(n))
	}
	data := g.refused("events/subscribe", params(domain.MaxExternalSubscriptions), api.EventsResourceExhausted,
		fmt.Sprintf("The workspace already has %d external subscriptions", domain.MaxExternalSubscriptions))
	if data["limit"] != "subscriptions" || data["max"] != domain.MaxExternalSubscriptions || len(g.cb.challenged) != 1 {
		t.Fatalf("data %v challenged %d", data, len(g.cb.challenged))
	}
	g.ok("events/subscribe", params(0))
}

func pyISO(t time.Time) string {
	s := t.UTC().Format("2006-01-02T15:04:05.000000")
	s = strings.TrimSuffix(s, ".000000")
	return s + "+00:00"
}
