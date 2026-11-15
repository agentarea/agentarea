//go:build suite

// Package streams pins /v1/workspaces/{workspace}/streams and /triggers
// (.omc/research/go-migration/dossiers/streams.md, section 2).
package streams

import (
	"net/http"
	"strings"
	"testing"
	"time"

	h "github.com/agentarea/agentarea/agentarea-go/test/suite/harness"
)

func TestMain(m *testing.M) { h.Main(m) }

func stream(w *h.Workspace, id any, name, description string) map[string]any {
	return map[string]any{"id": id, "name": name, "description": description, "kind": "custom",
		"created_by": w.People.Owner.ID, "created_at": h.AnyTimestamp}
}

func newStream(t *testing.T, w *h.Workspace, name string) string {
	t.Helper()
	return w.Owner.Post(t, w.Path("/streams/"), map[string]any{"name": name}).Expect(http.StatusCreated).Object()["id"].(string)
}

func TestStreamCreateReadListDelete(t *testing.T) {
	w := h.NewWorkspace(t)
	created := w.Owner.Post(t, w.Path("/streams/"), map[string]any{"name": "orders", "description": "shop"}).
		Expect(http.StatusCreated).Match(stream(w, h.AnyUUID, "orders", "shop")).Object()
	id := created["id"].(string)

	w.Owner.Get(t, w.Path("/streams/"+id)).Expect(http.StatusOK).Match(stream(w, id, "orders", "shop"))
	w.Owner.Get(t, w.Path("/streams/")).Expect(http.StatusOK).Match(h.Contains(stream(w, id, "orders", "shop")))
	w.Owner.Post(t, w.Path("/streams/"), map[string]any{"name": "orders"}).Expect(http.StatusConflict).
		Match(h.Problem(http.StatusConflict, "http_error", "A stream named 'orders' already exists in this workspace"))
	w.Owner.Post(t, w.Path("/streams/"), map[string]any{"name": "platform"}).Expect(http.StatusConflict).
		Match(h.Problem(http.StatusConflict, "http_error", "'platform' is the name of the workspace's platform stream"))
	w.Owner.Post(t, w.Path("/streams/"), map[string]any{"name": ""}).Expect(http.StatusUnprocessableEntity)

	w.Outsider.Get(t, w.OutsiderPath("/streams/")).Expect(http.StatusOK).Match([]any{})
	w.Outsider.Get(t, w.OutsiderPath("/streams/"+id)).Expect(http.StatusForbidden)
	w.Outsider.Get(t, w.Path("/streams/")).Expect(http.StatusForbidden)

	w.Owner.Delete(t, w.Path("/streams/"+id)).Expect(http.StatusNoContent)
	w.Owner.Get(t, w.Path("/streams/"+id)).Expect(http.StatusNotFound)
}

func TestForwardBlocksDeletingItsOutput(t *testing.T) {
	w := h.NewWorkspace(t)
	in, out := newStream(t, w, "in"), newStream(t, w, "out")

	w.Owner.Post(t, w.Path("/streams/"+in+"/forwards"), map[string]any{"output_stream_ids": []string{in}}).
		Expect(http.StatusBadRequest).Match(h.Problem(http.StatusBadRequest, "bad_request", "A forward may not write into its own input stream"))
	fwd := w.Owner.Post(t, w.Path("/streams/"+in+"/forwards"), map[string]any{
		"output_stream_ids": []string{out, out}, "event_filter": map[string]any{"kinds": []string{"order"}},
	}).Expect(http.StatusCreated).Match(map[string]any{
		"id": h.AnyUUID, "kind": "forward", "trigger_id": nil,
		"filter":            map[string]any{"kinds": []any{"order"}, "fields": map[string]any{}},
		"output_stream_ids": []any{out}, "status": "active", "code": nil, "created_at": h.AnyTimestamp,
	}).Object()
	fid := fwd["id"].(string)

	w.Owner.Get(t, w.Path("/streams/"+in+"/subscriptions")).Expect(http.StatusOK).Match([]any{fwd})
	resp := w.Owner.Delete(t, w.Path("/streams/"+out)).Expect(http.StatusConflict).Object()
	if !strings.Contains(resp["detail"].(string), "forward "+fid+" on stream "+in+" writes into it") {
		t.Fatalf("in-use detail = %v", resp["detail"])
	}
	w.Owner.Delete(t, w.Path("/streams/"+in+"/subscriptions/"+fid)).Expect(http.StatusNoContent)
	w.Owner.Delete(t, w.Path("/streams/"+out)).Expect(http.StatusNoContent)
}

func TestProcessorCodeIsChecked(t *testing.T) {
	w := h.NewWorkspace(t)
	in, out := newStream(t, w, "in"), newStream(t, w, "out")
	path := w.Path("/streams/" + in + "/processors")
	body := func(code string) map[string]any {
		return map[string]any{"output_stream_ids": []string{out}, "code": code}
	}

	w.Owner.Post(t, path, body("def process(event):\n    token = 'abc123'\n    return []\n")).Expect(http.StatusBadRequest).
		Match(h.Problem(http.StatusBadRequest, "bad_request", "Line 2 holds what looks like a secret. A processor gets no secrets, "+
			"and its code is shown to everyone who reads the stream"))
	w.Owner.Post(t, path, body("def handle(event):\n    return []\n")).Expect(http.StatusBadRequest).
		Match(h.Problem(http.StatusBadRequest, "bad_request",
			"The code must define a top-level def process(event) returning a list of events or None"))
	p := w.Owner.Post(t, path, body("def process(event):\n    return []\n")).Expect(http.StatusCreated).Object()
	id := p["id"].(string)
	w.Owner.Patch(t, path+"/"+id, map[string]any{"code": "def process(event):\n    return None\n"}).Expect(http.StatusOK)
	w.Owner.Delete(t, w.Path("/streams/"+in+"/subscriptions/"+id)).Expect(http.StatusConflict)
	w.Owner.Delete(t, path+"/"+id).Expect(http.StatusNoContent)
}

func TestEventsOfAnEmptyStream(t *testing.T) {
	w := h.NewWorkspace(t)
	id := newStream(t, w, "quiet")
	w.Owner.Get(t, w.Path("/streams/"+id+"/events")).Expect(http.StatusOK).
		Match(map[string]any{"events": []any{}, "next_after": nil, "next_before": nil})
	w.Owner.Get(t, w.Path("/streams/"+id+"/events?after=1&before=2")).Expect(http.StatusBadRequest).
		Match(h.Problem(http.StatusBadRequest, "bad_request", "Pass either after or before, not both"))
	w.Owner.Get(t, w.Path("/streams/"+id+"/events/999999999")).Expect(http.StatusNotFound).
		Match(h.Problem(http.StatusNotFound, "http_error", "Event 999999999 not found in stream"))
	w.Owner.Get(t, w.Path("/streams/events")).Expect(http.StatusOK).Match(map[string]any{
		"events": []any{}, "next_before": nil, "facets": h.Any,
	})

	live := w.Owner.Stream(t, w.Path("/streams/events/live"), 5*time.Second)
	defer live.Close()
}
