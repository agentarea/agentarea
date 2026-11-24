package mcpserver

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/go-chi/chi/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/mcpserve"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	identityapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	streamsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
)

// scopeProbe answers events/list with the workspaces its scope reaches and events/poll with
// the workspace params.name entered.
type scopeProbe struct{}

func (scopeProbe) Serve(ctx context.Context, s streamsapi.EventsScope, method string, params json.RawMessage) (any, error) {
	switch method {
	case "events/list":
		callers, err := s.Workspaces(ctx)
		if err != nil {
			return nil, err
		}
		var ids []string
		for _, c := range callers {
			ids = append(ids, c.Workspace.Slug())
		}
		return map[string]any{"workspaces": ids}, nil
	case "events/poll":
		var p struct {
			Name string `json:"name"`
		}
		if err := json.Unmarshal(params, &p); err != nil {
			return nil, err
		}
		c, err := s.Enter(ctx, p.Name)
		if err != nil {
			return nil, err
		}
		return map[string]any{"entered": c.Workspace.ID(), "user": c.UserID}, nil
	}
	return nil, &streamsapi.EventsError{Code: CodeMethodNotFound, Message: "Method not found"}
}

type reachable struct{ identityapi.Members }

func (reachable) ListWorkspaces(context.Context, authn.Principal) ([]identityapi.Workspace, error) {
	return []identityapi.Workspace{{ID: wsID, Slug: "acme"}}, nil
}

func eventsServer(t *testing.T, events *Events) *chi.Mux {
	t.Helper()
	auth := Auth{Gate: gate(), APIURL: "https://api.example/"}
	r := chi.NewRouter()
	for _, spanning := range []bool{true, false} {
		p := NewPlatform(spanning, Identity("https://api.example", PlatformName, PlatformInstructions), auth, nil)
		p.UseEvents(events)
		mount := mcpserve.MountSpan
		if !spanning {
			mount = mcpserve.MountPinned
		}
		r.Handle(mount, p.Handler(mount))
	}
	return r
}

func rpcError(r rpcReply) map[string]any {
	e, _ := r.body["error"].(map[string]any)
	return e
}

func TestEventsAreAdvertisedAndServedOnEveryPlatformMount(t *testing.T) {
	h := eventsServer(t, &Events{Server: scopeProbe{}, Members: reachable{}})
	r := call(t, h, "/mcp", "", `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}`, nil)
	caps := r.body["result"].(map[string]any)["capabilities"].(map[string]any)
	ext, _ := caps["extensions"].(map[string]any)
	if got, _ := json.Marshal(ext[EventsExtension]); string(got) != `{"listChanged":false}` {
		t.Fatalf("extensions %v", caps)
	}
	if got, _ := json.Marshal(caps["events"]); string(got) != `{"listChanged":false}` {
		t.Fatalf("sketch capability %v", caps)
	}

	r = call(t, h, "/mcp/w/acme", "user", `{"jsonrpc":"2.0","id":2,"method":"events/poll","params":{"name":"acme"}}`, nil)
	if res, _ := r.body["result"].(map[string]any); r.status != 200 || res["entered"] != wsID || res["user"] != "u1" {
		t.Fatalf("pinned poll %d %v", r.status, r.body)
	}
	r = call(t, h, "/mcp/w/acme", "user", `{"jsonrpc":"2.0","id":3,"method":"events/poll","params":{"name":"`+wsID+`"}}`, nil)
	if res, _ := r.body["result"].(map[string]any); res["entered"] != wsID {
		t.Fatalf("pinned by id %v", r.body)
	}
	r = call(t, h, "/mcp/w/acme", "user", `{"jsonrpc":"2.0","id":4,"method":"events/poll","params":{"name":"other"}}`, nil)
	if e := rpcError(r); r.status != 200 || e["code"] != float64(streamsapi.EventsNotFound) || e["message"] != "no such event type here" ||
		e["data"].(map[string]any)["kind"] != "event" {
		t.Fatalf("pinned elsewhere %d %v", r.status, r.body)
	}

	r = call(t, h, "/mcp", "user", `{"jsonrpc":"2.0","id":5,"method":"events/list"}`, nil)
	if got, _ := json.Marshal(r.body["result"]); string(got) != `{"workspaces":["acme"]}` {
		t.Fatalf("spanning list %v", r.body)
	}
	r = call(t, h, "/mcp", "user", `{"jsonrpc":"2.0","id":6,"method":"events/poll","params":{"name":"acme"}}`, nil)
	if res, _ := r.body["result"].(map[string]any); res["entered"] != wsID {
		t.Fatalf("spanning poll %v", r.body)
	}
	r = call(t, h, "/mcp", "user", `{"jsonrpc":"2.0","id":7,"method":"events/poll","params":{"name":"other"}}`, nil)
	if e := rpcError(r); e["code"] != float64(streamsapi.EventsForbidden) || e["message"] != "no accessible workspace 'other'" {
		t.Fatalf("spanning elsewhere %v", r.body)
	}

	if r := call(t, h, "/mcp", "", `{"jsonrpc":"2.0","id":8,"method":"events/list"}`, nil); r.status != 401 {
		t.Fatalf("anonymous list %d", r.status)
	}
	if r := call(t, h, "/mcp", "user", `{"jsonrpc":"2.0","id":9,"method":"events/stream"}`, nil); errCode(r) != CodeMethodNotFound {
		t.Fatalf("events/stream %v", r.body)
	}
}

func TestWithoutEventsNothingIsAdvertisedOrServed(t *testing.T) {
	h := eventsServer(t, nil)
	r := call(t, h, "/mcp", "", `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}`, nil)
	caps := r.body["result"].(map[string]any)["capabilities"].(map[string]any)
	if _, ok := caps["events"]; ok {
		t.Fatalf("advertised %v", caps)
	}
	if r := call(t, h, "/mcp", "user", `{"jsonrpc":"2.0","id":2,"method":"events/list"}`, nil); errCode(r) != CodeMethodNotFound {
		t.Fatalf("list %v", r.body)
	}
}

func TestClientEventsScopeIsTheClientsWorkspace(t *testing.T) {
	ctx := context.Background()
	ws, _ := scope.NewWorkspace(wsID, "acme")
	c := authn.Caller{Principal: authn.Principal{UserID: "u1"}, Workspace: ws}
	in := ClientEventsScope(func(context.Context) (authn.Caller, bool, error) { return c, true, nil })
	if got, err := in.Workspaces(ctx); err != nil || len(got) != 1 || got[0].Workspace.ID() != wsID {
		t.Fatalf("workspaces %v %v", got, err)
	}
	if got, err := in.Enter(ctx, "acme"); err != nil || got.UserID != "u1" {
		t.Fatalf("enter %v %v", got, err)
	}
	var e *streamsapi.EventsError
	if _, err := in.Enter(ctx, "other"); !errors.As(err, &e) || e.Code != streamsapi.EventsNotFound {
		t.Fatalf("elsewhere %v", err)
	}
	out := ClientEventsScope(func(context.Context) (authn.Caller, bool, error) { return authn.Caller{}, false, nil })
	if _, err := out.Workspaces(ctx); !errors.As(err, &e) || e.Code != streamsapi.EventsForbidden || e.Message != "not authorized for this client" {
		t.Fatalf("refused %v", err)
	}
}
