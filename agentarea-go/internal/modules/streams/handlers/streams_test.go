package handlers_test

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/handlers"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store/storetest"
)

type streamRig struct {
	t     *testing.T
	h     http.Handler
	ws    scope.Workspace
	db    storetest.DB
	graph *storetest.Graph
}

func newStreamRig(t *testing.T) *streamRig {
	t.Helper()
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	graph := &storetest.Graph{AllowAll: true}
	svc := service.New(service.Deps{DB: storetest.DB{Pool: pool}, Graph: graph, Agents: storetest.Agents{}})
	errs := httpx.NewErrors("http://api.test", slog.Default(), handlers.MapError)
	r := chi.NewRouter()
	caller := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
			ctx := authn.WithCaller(req.Context(), authn.Caller{Principal: authn.Principal{UserID: "u1"}, Workspace: ws})
			next.ServeHTTP(w, req.WithContext(ctx))
		})
	}
	handlers.Mount(r, errs, caller, handlers.New(svc, nil, nil))
	return &streamRig{t: t, h: r, ws: ws, db: storetest.DB{Pool: pool}, graph: graph}
}

func (g *streamRig) do(method, path string, body any) *httptest.ResponseRecorder {
	g.t.Helper()
	var buf bytes.Buffer
	if body != nil {
		if err := json.NewEncoder(&buf).Encode(body); err != nil {
			g.t.Fatal(err)
		}
	}
	req := httptest.NewRequest(method, "/v1/workspaces/"+g.ws.ID()+"/streams"+path, &buf)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	g.h.ServeHTTP(rec, req)
	return rec
}

func (g *streamRig) expect(rec *httptest.ResponseRecorder, code int, detail string) map[string]any {
	g.t.Helper()
	if rec.Code != code {
		g.t.Fatalf("status = %d, want %d: %s", rec.Code, code, rec.Body.String())
	}
	if detail != "" && !strings.Contains(rec.Body.String(), detail) {
		g.t.Fatalf("body %s lacks %q", rec.Body.String(), detail)
	}
	var m map[string]any
	_ = json.Unmarshal(rec.Body.Bytes(), &m)
	return m
}

func (g *streamRig) stream(name string) string {
	g.t.Helper()
	m := g.expect(g.do(http.MethodPost, "/", map[string]any{"name": name}), http.StatusCreated, "")
	id := m["id"].(string)
	g.graph.Readable = append(g.graph.Readable, id)
	return id
}

func (g *streamRig) event(streamID, kind string, data map[string]any) domain.Event {
	g.t.Helper()
	now := time.Now().UTC()
	e := domain.Event{ID: uuid.NewString(), Kind: kind, Source: "test", OccurredAt: now, Data: data, StreamID: streamID,
		WorkspaceID: g.ws.ID(), CreatedBy: "u1", EventKey: uuid.NewString(), ReceivedAt: now}
	ok, err := store.Streams{}.RecordEvent(context.Background(), db.NewSession(g.ws, g.db.Pool), e)
	if err != nil || !ok {
		g.t.Fatalf("record = %v, %v", ok, err)
	}
	return e
}

func TestStreamsCRUDAndInUse(t *testing.T) {
	g := newStreamRig(t)
	a, b := g.stream("orders"), g.stream("copies")
	g.expect(g.do(http.MethodPost, "/", map[string]any{"name": "orders"}), http.StatusConflict, "A stream named 'orders' already exists")
	g.expect(g.do(http.MethodPost, "/", map[string]any{"name": "platform"}), http.StatusConflict, "is the name of the workspace's platform stream")
	g.expect(g.do(http.MethodPost, "/", map[string]any{"name": ""}), http.StatusUnprocessableEntity, "")

	var listed []map[string]any
	if err := json.Unmarshal(g.do(http.MethodGet, "/", nil).Body.Bytes(), &listed); err != nil || len(listed) != 2 {
		t.Fatalf("list = %v %v", listed, err)
	}
	g.graph.Readable = []string{a}
	_ = json.Unmarshal(g.do(http.MethodGet, "/", nil).Body.Bytes(), &listed)
	if len(listed) != 1 || listed[0]["id"] != a {
		t.Fatalf("narrowed list = %v", listed)
	}
	g.graph.Readable = []string{a, b}

	g.expect(g.do(http.MethodPost, "/"+a+"/forwards", map[string]any{"output_stream_ids": []string{}}), http.StatusUnprocessableEntity, "")
	g.expect(g.do(http.MethodPost, "/"+a+"/forwards", map[string]any{"output_stream_ids": []string{a}}), http.StatusBadRequest,
		"A forward may not write into its own input stream")
	missing := uuid.NewString()
	g.expect(g.do(http.MethodPost, "/"+a+"/forwards", map[string]any{"output_stream_ids": []string{missing}}), http.StatusNotFound,
		"Stream "+missing+" not found")
	fwd := g.expect(g.do(http.MethodPost, "/"+a+"/forwards", map[string]any{"output_stream_ids": []string{b, b},
		"event_filter": map[string]any{"kinds": []string{"order"}}}), http.StatusCreated, "")
	if outs := fwd["output_stream_ids"].([]any); len(outs) != 1 || fwd["kind"] != "forward" {
		t.Fatalf("forward = %v", fwd)
	}
	if f := fwd["filter"].(map[string]any); f["fields"] == nil || len(f["kinds"].([]any)) != 1 {
		t.Fatalf("stored filter = %v", f)
	}
	g.expect(g.do(http.MethodDelete, "/"+b, nil), http.StatusConflict, "Stream "+b+" is in use: forward "+fwd["id"].(string)+" on stream "+a)
	var subs []map[string]any
	_ = json.Unmarshal(g.do(http.MethodGet, "/"+a+"/subscriptions", nil).Body.Bytes(), &subs)
	if len(subs) != 1 {
		t.Fatalf("subscriptions = %v", subs)
	}
	var outbox int
	if err := g.db.Pool.QueryRow(context.Background(),
		`SELECT count(*) FROM event_outbox WHERE event_type = 'streams.subscriptions.changed' AND workspace_id = $1`, g.ws.ID()).Scan(&outbox); err != nil || outbox != 1 {
		t.Fatalf("outbox notices = %d, %v", outbox, err)
	}
	g.expect(g.do(http.MethodDelete, "/"+a+"/processors/"+fwd["id"].(string), nil), http.StatusConflict, "is not a processor")
	g.expect(g.do(http.MethodDelete, "/"+a+"/subscriptions/"+fwd["id"].(string), nil), http.StatusNoContent, "")
	g.expect(g.do(http.MethodDelete, "/"+b, nil), http.StatusNoContent, "")
	g.expect(g.do(http.MethodGet, "/"+b, nil), http.StatusNotFound, "Stream "+b+" not found")
}

func TestStreamRoutesNeedPermission(t *testing.T) {
	g := newStreamRig(t)
	a := g.stream("orders")
	g.graph.AllowAll = false
	g.expect(g.do(http.MethodGet, "/"+a, nil), http.StatusForbidden, "")
	g.graph.Grant("User:u1", "can_read", a)
	g.expect(g.do(http.MethodGet, "/"+a, nil), http.StatusOK, "")
	g.expect(g.do(http.MethodDelete, "/"+a, nil), http.StatusForbidden, "")
	b := uuid.NewString()
	g.graph.Grant("User:u1", "can_write", a)
	g.expect(g.do(http.MethodPost, "/"+a+"/forwards", map[string]any{"output_stream_ids": []string{b}}), http.StatusForbidden, "")
}

func TestProcessors(t *testing.T) {
	g := newStreamRig(t)
	a, b := g.stream("in"), g.stream("out")
	body := func(code string) map[string]any {
		return map[string]any{"output_stream_ids": []string{b}, "code": code}
	}
	g.expect(g.do(http.MethodPost, "/"+a+"/processors", body("def nope(e):\n    pass\n")), http.StatusBadRequest,
		"The code must define a top-level def process(event)")
	g.expect(g.do(http.MethodPost, "/"+a+"/processors", body("def process(e):\n    api_key = 'abc'\n")), http.StatusBadRequest,
		"Line 2 holds what looks like a secret")
	g.expect(g.do(http.MethodPost, "/"+a+"/processors", map[string]any{"output_stream_ids": []string{a}, "code": "def process(e): pass"}),
		http.StatusBadRequest, "A processor may not write into its own input stream")
	p := g.expect(g.do(http.MethodPost, "/"+a+"/processors", body("def process(e):\n    return []\n")), http.StatusCreated, "")
	id := p["id"].(string)
	if p["kind"] != "processor" || !strings.Contains(p["code"].(string), "def process") {
		t.Fatalf("processor = %v", p)
	}
	u := g.expect(g.do(http.MethodPatch, "/"+a+"/processors/"+id, map[string]any{"code": "def process(event):\n    return None\n",
		"event_filter": map[string]any{"kinds": []string{"x"}}}), http.StatusOK, "")
	if !strings.Contains(u["code"].(string), "return None") || len(u["filter"].(map[string]any)["kinds"].([]any)) != 1 {
		t.Fatalf("updated = %v", u)
	}
	g.expect(g.do(http.MethodPatch, "/"+a+"/processors/"+id, map[string]any{"code": "def process(e):\n  x = (1\n"}),
		http.StatusBadRequest, "The code does not parse: '(' was never closed (line 2)")
	g.expect(g.do(http.MethodDelete, "/"+b, nil), http.StatusConflict, "processor "+id+" on stream "+a+" writes into it")
	g.expect(g.do(http.MethodDelete, "/"+a+"/subscriptions/"+id, nil), http.StatusConflict, "Subscription "+id+" is a processor, not a forward")
	g.expect(g.do(http.MethodDelete, "/"+a+"/processors/"+id, nil), http.StatusNoContent, "")
	g.expect(g.do(http.MethodDelete, "/"+a+"/processors/"+id, nil), http.StatusNotFound, "Subscription "+id+" not found")
}

func TestEventsReads(t *testing.T) {
	g := newStreamRig(t)
	a := g.stream("orders")
	first := g.event(a, "order.paid", map[string]any{"body": map[string]any{"n": 1.0}})
	g.event(a, "order.refunded", map[string]any{"body": map[string]any{"n": 2.0}})

	g.expect(g.do(http.MethodGet, "/"+a+"/events?after=0&before=5", nil), http.StatusBadRequest, "Pass either after or before, not both")
	page := g.expect(g.do(http.MethodGet, "/"+a+"/events?after=0&limit=1", nil), http.StatusOK, "")
	evs := page["events"].([]any)
	seq := evs[0].(map[string]any)["sequence"].(float64)
	if len(evs) != 1 || evs[0].(map[string]any)["event_id"] != first.ID || page["next_after"] != seq || page["next_before"] != nil {
		t.Fatalf("page = %v", page)
	}
	seqPath := strconv.FormatInt(int64(seq), 10)
	newest := g.expect(g.do(http.MethodGet, "/"+a+"/events", nil), http.StatusOK, "")
	if evs := newest["events"].([]any); len(evs) != 2 || evs[0].(map[string]any)["kind"] != "order.refunded" {
		t.Fatalf("newest first = %v", newest)
	}
	d := g.expect(g.do(http.MethodGet, "/"+a+"/events/"+seqPath, nil), http.StatusOK, "")
	if d["event_id"] != first.ID || d["v"] != 1.0 || d["handlers"] == nil || d["processing"].(map[string]any)["status"] != "queued" {
		t.Fatalf("detail = %v", d)
	}
	g.expect(g.do(http.MethodGet, "/"+a+"/events/"+strconv.FormatInt(int64(seq)+100000, 10), nil), http.StatusNotFound, "not found in stream")
	g.expect(g.do(http.MethodGet, "/"+a+"/events/0", nil), http.StatusUnprocessableEntity, "")
	byID := g.expect(g.do(http.MethodGet, "/events/"+first.ID, nil), http.StatusOK, "")
	if byID["sequence"] != seq {
		t.Fatalf("by id = %v", byID)
	}
	missing := uuid.NewString()
	g.expect(g.do(http.MethodGet, "/events/"+missing, nil), http.StatusNotFound, "Event "+missing+" not found")

	feed := g.expect(g.do(http.MethodGet, "/events?kind=order.*&limit=1", nil), http.StatusOK, "")
	if evs := feed["events"].([]any); len(evs) != 1 || feed["next_before"] == nil || feed["facets"] == nil {
		t.Fatalf("feed = %v", feed)
	}
	next := g.expect(g.do(http.MethodGet, "/events?before="+seqPath, nil), http.StatusOK, "")
	if next["facets"] != nil {
		t.Fatalf("facets on a later page = %v", next)
	}
	g.graph.Readable = nil
	empty := g.expect(g.do(http.MethodGet, "/events", nil), http.StatusOK, "")
	if len(empty["events"].([]any)) != 0 {
		t.Fatalf("unreadable streams in feed = %v", empty)
	}
	g.expect(g.do(http.MethodGet, "/"+a+"/subscriptions/"+uuid.NewString()+"/outcomes", nil), http.StatusNotFound, "Subscription not found in stream")
	g.expect(g.do(http.MethodGet, "/events/live", nil), http.StatusServiceUnavailable, "")
}
