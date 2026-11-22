package service

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/mcpserve"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/mcpserver"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
)

const clientWS = "22222222-2222-2222-2222-222222222222"

type fakeBundles struct {
	ws     string
	bundle agentsapi.ClientBundle
}

func (f fakeBundles) Locate(_ context.Context, _ string, workspaces []string) (string, bool, error) {
	for _, w := range workspaces {
		if w == f.ws {
			return w, true, nil
		}
	}
	return "", false, nil
}

func (f fakeBundles) Bundle(context.Context, scope.Workspace, string, string) (agentsapi.ClientBundle, bool, error) {
	return f.bundle, true, nil
}

type fakePolicies struct {
	governanceapi.ToolPolicies
	policy governanceapi.Policy
}

func (f fakePolicies) Effective(context.Context, scope.Workspace, string) (governanceapi.Policy, error) {
	return f.policy, nil
}

type fakeAudit struct{ rows []governanceapi.AuditRecord }

func (f *fakeAudit) RecordOnce(_ context.Context, _ db.Session, rec governanceapi.AuditRecord) error {
	f.rows = append(f.rows, rec)
	return nil
}

// useGraph grants can_read (use) on the resources it names.
type useGraph struct {
	memGraph
	readable map[string]bool
}

func (g useGraph) Check(_ context.Context, _, relation, _, id string) (bool, error) {
	return relation == "can_read" && g.readable[id], nil
}

type fakeCarrier struct{ called []string }

func (f *fakeCarrier) Carried(context.Context, authn.Caller, []agentsapi.ClientToolset) ([]mcpserver.Tool, error) {
	return []mcpserver.Tool{
		{Tool: mcpserve.Tool{Name: "agents_list", InputSchema: json.RawMessage(`{"type":"object"}`)}},
		{Tool: mcpserve.Tool{Name: "secrets_delete", InputSchema: json.RawMessage(`{"type":"object"}`)}},
	}, nil
}

func (f *fakeCarrier) CallCarried(_ context.Context, _ authn.Caller, name string, _ json.RawMessage) (any, error) {
	f.called = append(f.called, name)
	return mcpserve.Result{Content: []mcpserve.Content{{Type: "text", Text: "ran " + name}}}, nil
}

func enterClientWS(_ context.Context, p authn.Principal, ref string) (authn.Caller, error) {
	ws, err := scope.NewWorkspace(ref, "acme")
	if err != nil {
		return authn.Caller{}, err
	}
	return authn.Caller{Principal: p, Workspace: ws}, nil
}

type clientFixture struct {
	svc      *Service
	audit    *fakeAudit
	carrier  *fakeCarrier
	clientID string
	connID   uuid.UUID
}

func newClientFixture(t *testing.T, denied []string) clientFixture {
	t.Helper()
	clientID, connID := uuid.NewString(), uuid.New()
	conns := &memConns{rows: map[uuid.UUID]domain.Connection{connID: {
		ID: connID.String(), Name: "Billing API",
		AvailableTools: []domain.Tool{{Name: "list invoices", Description: "List"}, {Name: "void"}},
	}}}
	f := clientFixture{audit: &fakeAudit{}, carrier: &fakeCarrier{}, clientID: clientID, connID: connID}
	f.svc = New(Deps{Stamps: NewStamps(), Verdicts: NewVerdicts(),
		DB: memDB{}, Connections: conns, Instances: manyInstances{},
		Graph:    useGraph{readable: map[string]bool{clientID: true}},
		Policies: fakePolicies{policy: governanceapi.Policy{Tools: &governanceapi.Tools{Denied: denied}}},
		Audit:    f.audit,
		ClientBundles: fakeBundles{ws: clientWS, bundle: agentsapi.ClientBundle{
			ID: clientID, Name: "Desk",
			OpenAPI:  []agentsapi.ClientAttachment{{ID: connID.String(), AllowedTools: []string{"list invoices"}}},
			Toolsets: []agentsapi.ClientToolset{{Toolset: "agentarea/agents"}},
			Skills:   []agentsapi.ClientSkill{{ID: "s1", Name: "triage", Description: "Triage", Content: "Do triage."}},
		}},
	})
	return f
}

type manyInstances struct{ InstanceStore }

func (manyInstances) GetMany(context.Context, db.Session, []uuid.UUID) (map[string]domain.Instance, error) {
	return map[string]domain.Instance{}, nil
}

func (f clientFixture) backend(t *testing.T, p authn.Principal) mcpserver.Backend {
	t.Helper()
	b, err := f.svc.ClientEndpoint(context.Background(), p, f.clientID, enterClientWS, f.carrier)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func workspaceMember() authn.Principal {
	return authn.Principal{UserID: "u1", AccessibleWorkspaces: []string{clientWS}}
}

func TestClientEndpointListsBundleAndHidesDenied(t *testing.T) {
	f := newClientFixture(t, []string{"secrets_delete"})
	tools, err := f.backend(t, workspaceMember()).ListTools(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	var names []string
	for _, tool := range tools {
		names = append(names, tool.Name)
	}
	want := []string{"billing_api__list_invoices", "agents_list", ActivateSkillTool}
	if len(names) != len(want) {
		t.Fatalf("tools = %v", names)
	}
	for _, w := range want {
		found := false
		for _, n := range names {
			found = found || n == w
		}
		if !found {
			t.Fatalf("tools = %v, missing %s", names, w)
		}
	}
}

func TestClientEndpointAuditsEachVerdict(t *testing.T) {
	f := newClientFixture(t, []string{"secrets_delete"})
	b := f.backend(t, workspaceMember())
	if _, err := b.CallTool(context.Background(), "agents_list", json.RawMessage(`{"q":1}`)); err != nil {
		t.Fatal(err)
	}
	out, err := b.CallTool(context.Background(), "secrets_delete", json.RawMessage(`{}`))
	if err != nil {
		t.Fatal(err)
	}
	res := out.(mcpserve.Result)
	if !res.IsError || res.Content[0].Text != "Tool call refused: tool 'secrets_delete' is denied by policy" {
		t.Fatalf("refusal = %+v", res)
	}
	if len(f.carrier.called) != 1 || f.carrier.called[0] != "agents_list" {
		t.Fatalf("called = %v", f.carrier.called)
	}
	if len(f.audit.rows) != 2 || f.audit.rows[0].Action != "tool.call.allowed" || f.audit.rows[1].Action != "tool.call.denied" {
		t.Fatalf("audit = %+v", f.audit.rows)
	}
	first := f.audit.rows[0]
	if first.ResourceType != "client" || first.ResourceID != f.clientID || first.ActorType != "user" {
		t.Fatalf("audit row = %+v", first)
	}
	if keys := first.Metadata["argument_keys"].([]string); len(keys) != 1 || keys[0] != "q" {
		t.Fatalf("argument_keys = %v", first.Metadata["argument_keys"])
	}
}

func TestClientEndpointActivatesSkills(t *testing.T) {
	f := newClientFixture(t, nil)
	b := f.backend(t, workspaceMember())
	for arg, want := range map[string]string{
		"triage": "<skill_content name=\"triage\">\nDo triage.</skill_content>",
		"nope":   "Unknown skill 'nope'. Available: triage",
	} {
		out, err := b.CallTool(context.Background(), ActivateSkillTool, json.RawMessage(`{"skill_name":"`+arg+`"}`))
		if err != nil {
			t.Fatal(err)
		}
		if got := out.(mcpserve.Result).Content[0].Text; got != want {
			t.Fatalf("%s: %q", arg, got)
		}
	}
	if len(f.audit.rows) != 0 {
		t.Fatalf("skill activation audited: %+v", f.audit.rows)
	}
}

func TestClientEndpointAuthorization(t *testing.T) {
	f := newClientFixture(t, nil)
	ctx := context.Background()

	outsider := authn.Principal{UserID: "u2", AccessibleWorkspaces: []string{"33333333-3333-3333-3333-333333333333"}}
	b, err := f.svc.ClientEndpoint(ctx, outsider, f.clientID, enterClientWS, f.carrier)
	if err != nil {
		t.Fatal(err)
	}
	if tools, _ := b.ListTools(ctx); len(tools) != 0 {
		t.Fatalf("outsider sees %v", tools)
	}
	if _, err := b.CallTool(ctx, "agents_list", nil); err == nil || err.Error() != "Client not found" {
		t.Fatalf("outsider call: %v", err)
	}

	denied := []authn.Principal{
		{UserID: "u1", AccessibleWorkspaces: []string{clientWS}, BoundTaskID: "t1", TurnClientID: uuid.NewString()},
	}
	g := useGraph{readable: map[string]bool{}}
	f.svc.d.Graph = g
	f.svc.perms = New(Deps{Stamps: NewStamps(), Verdicts: NewVerdicts(), Graph: g}).perms
	denied = append(denied, workspaceMember())
	for _, p := range denied {
		_, err := f.svc.ClientEndpoint(ctx, p, f.clientID, enterClientWS, f.carrier)
		var refusal *mcpserver.Refusal
		if !errors.As(err, &refusal) || refusal.Msg != "Not authorized for this client" {
			t.Fatalf("%+v: %v", p, err)
		}
	}

	allowed := []authn.Principal{
		{UserID: "u1", AccessibleWorkspaces: []string{clientWS}, ClientID: f.clientID},
		{UserID: "u1", AccessibleWorkspaces: []string{clientWS}, BoundTaskID: "t1", TurnClientID: f.clientID},
	}
	for _, p := range allowed {
		if _, err := f.svc.ClientEndpoint(ctx, p, f.clientID, enterClientWS, f.carrier); err != nil {
			t.Fatalf("%+v: %v", p, err)
		}
	}

	if _, err := f.svc.ClientEndpoint(ctx, workspaceMember(), "not-a-uuid", enterClientWS, f.carrier); err != nil {
		t.Fatalf("bad id: %v", err)
	}
}

func TestJudgeProxyRequest(t *testing.T) {
	svc := New(Deps{Stamps: NewStamps(), Verdicts: NewVerdicts(), Policies: fakePolicies{policy: governanceapi.Policy{Tools: &governanceapi.Tools{Denied: []string{"mcp:inst-1:wipe"}}}}})
	ws, _ := scope.NewWorkspace(clientWS, "acme")
	c := authn.Caller{Principal: authn.Principal{UserID: "u1"}, Workspace: ws}
	ctx := context.Background()
	call := func(name string) []byte {
		return []byte(`{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"` + name + `"}}`)
	}

	if err := svc.JudgeProxyRequest(ctx, c, "inst-1", call("read"), http.Header{}); err != nil {
		t.Fatalf("allowed: %v", err)
	}
	if err := svc.JudgeProxyRequest(ctx, c, "inst-1", []byte("not json"), http.Header{}); err != nil {
		t.Fatalf("opaque body: %v", err)
	}

	var refusal *ProxyRefusal
	err := svc.JudgeProxyRequest(ctx, c, "inst-1", call("wipe"), http.Header{})
	if !errors.As(err, &refusal) || refusal.Status != 403 || refusal.Detail != "Tool call denied: wipe: tool 'mcp:inst-1:wipe' is denied by policy" {
		t.Fatalf("denied: %v", err)
	}
	err = svc.JudgeProxyRequest(ctx, c, "inst-1", []byte(`{"jsonrpc":"2.0","id":1,"method":"events/subscribe","params":{"name":"x"}}`), http.Header{})
	if !errors.As(err, &refusal) || refusal.Status != 403 {
		t.Fatalf("subscribe: %v", err)
	}

	h := http.Header{}
	h.Set(mcpserver.HeaderMethod, "tools/call")
	h.Set(mcpserver.HeaderName, "other")
	err = svc.JudgeProxyRequest(ctx, c, "inst-1", call("read"), h)
	if !errors.As(err, &refusal) || refusal.Status != 400 {
		t.Fatalf("name mismatch: %v", err)
	}
	body := refusal.Body.(map[string]any)
	if body["id"] != float64(4) || body["error"].(map[string]any)["message"] != "Header mismatch: Mcp-Name header value 'other' does not match body value 'read'" {
		t.Fatalf("mismatch body: %v", body)
	}
	h.Set(mcpserver.HeaderName, "read")
	if err := svc.JudgeProxyRequest(ctx, c, "inst-1", call("read"), h); err != nil {
		t.Fatalf("matching headers: %v", err)
	}
	h.Set(mcpserver.HeaderMethod, "tools/list")
	err = svc.JudgeProxyRequest(ctx, c, "inst-1", call("read"), h)
	if !errors.As(err, &refusal) || refusal.Detail != "Header mismatch: Mcp-Method header value 'tools/list' does not match body value 'tools/call'" {
		t.Fatalf("method mismatch: %v", err)
	}
}

func TestSingleToolCall(t *testing.T) {
	for body, want := range map[string]string{
		`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"a"}}`:                          "a",
		`[{"method":"tools/call","params":{"name":"a"}},{"method":"tools/call","params":{"name":"b"}}]`: "",
		`{"method":"tools/list"}`: "",
		``:                        "",
	} {
		if got := SingleToolCall([]byte(body)); got != want {
			t.Fatalf("%s: %q", body, got)
		}
	}
}

// Python ran a client bundle's OpenAPI tool through the connection proxy's
// check: the bundle's own verdict (rules on openapi:<connection>:<tool>) was
// never applied and the call was never audited.
func TestClientEndpointJudgesAndAuditsOpenAPICalls(t *testing.T) {
	f := newClientFixture(t, nil)
	conn := f.svc.d.Connections.(*memConns).rows[f.connID]
	f.svc.d.OpenAPIWrites = &writesStore{rows: map[uuid.UUID]domain.Connection{f.connID: conn}, dispatch: map[uuid.UUID]map[string]any{}}
	target := "openapi:" + f.connID.String() + ":list_invoices"
	for _, tc := range []struct {
		tools  governanceapi.Tools
		action string
	}{
		{governanceapi.Tools{Denied: []string{target}}, "tool.call.denied"},
		{governanceapi.Tools{Allowed: []string{"list_invoices"}}, "tool.call.denied"},
		{governanceapi.Tools{Allowed: []string{target}}, "tool.call.allowed"},
	} {
		f.svc.d.Policies = fakePolicies{policy: governanceapi.Policy{Tools: &tc.tools}}
		f.audit.rows = nil
		out, err := f.backend(t, workspaceMember()).CallTool(context.Background(), "billing_api__list_invoices", json.RawMessage(`{"a":1}`))
		if err != nil {
			t.Fatal(err)
		}
		res := out.(mcpserve.Result)
		refused := res.IsError && len(res.Content) == 1 && strings.HasPrefix(res.Content[0].Text, "Tool call refused: ")
		if refused != (tc.action == "tool.call.denied") {
			t.Fatalf("%+v: result = %+v", tc.tools, res)
		}
		if len(f.audit.rows) != 1 || f.audit.rows[0].Action != tc.action || f.audit.rows[0].Metadata["openapi_connection_id"] != f.connID.String() {
			t.Fatalf("%+v: audit = %+v", tc.tools, f.audit.rows)
		}
	}
}
