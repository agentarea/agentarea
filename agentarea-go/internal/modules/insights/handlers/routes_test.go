package handlers

import (
	"context"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	connectionsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/insights/service"
	streamsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/api"
)

// reads fakes the reads the routes below touch; the rest stay nil.
type reads struct {
	agentsapi.Network
	agentsapi.Lookup
	connectionsapi.ConnectionBoard
	streamsapi.Triggers
	governanceapi.SpendCaps

	cap    *money.Decimal
	set    []*money.Decimal
	capErr error
}

func (r *reads) AgentExists(context.Context, scope.Workspace, string) (bool, error) {
	return false, nil
}

func (r *reads) MonthlyCap(context.Context, scope.Workspace) (*money.Decimal, error) {
	return r.cap, nil
}

func (r *reads) SetMonthlyCap(_ context.Context, _ authn.Caller, amount *money.Decimal) error {
	r.set = append(r.set, amount)
	return r.capErr
}

func (r *reads) NetworkAgents(context.Context, scope.Workspace) ([]agentsapi.NetworkAgent, error) {
	return []agentsapi.NetworkAgent{{ID: "a1", Name: "Scout", Status: "active"}}, nil
}

func (r *reads) NetworkSkills(context.Context, scope.Workspace) ([]agentsapi.NetworkSkill, []agentsapi.SkillMember, error) {
	return nil, nil, nil
}

func (r *reads) MCPInstances(context.Context, scope.Workspace) ([]connectionsapi.MCPInstanceState, error) {
	return nil, nil
}

func (r *reads) OpenAPIConnections(context.Context, scope.Workspace) ([]connectionsapi.OpenAPIState, error) {
	return nil, nil
}

func (r *reads) ListTriggers(context.Context, scope.Workspace, *string) ([]streamsapi.TriggerSummary, error) {
	return []streamsapi.TriggerSummary{{ID: "t1", Name: "Daily", AgentID: "a1", TriggerType: "cron", IsActive: true}}, nil
}

func withReads(r *reads, admin error) *service.Service {
	return svc(service.Deps{Admin: func(context.Context) error { return admin },
		Reads: service.Reads{Agents: r, Lookup: r, Connections: r, AllTriggers: r, Caps: r}})
}

func put(t *testing.T, url, contentType, body string) (int, string) {
	t.Helper()
	req, err := http.NewRequest(http.MethodPut, url, strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	b, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, string(b)
}

func TestOverviewUnknownAgentIs404(t *testing.T) {
	srv := server(t, withReads(&reads{}, nil))
	code, body := get(t, srv, "/v1/workspaces/acme/agents/"+uuid.NewString()+"/overview")
	if code != http.StatusNotFound || !strings.Contains(body, `"detail":"Agent not found"`) {
		t.Fatalf("got %d %s", code, body)
	}
	if code, body := get(t, srv, "/v1/workspaces/acme/agents/not-a-uuid/overview"); code != http.StatusUnprocessableEntity || !strings.Contains(body, `"type":"uuid_parsing","loc":["path","agent_id"]`) {
		t.Fatalf("a malformed id answered %d %s", code, body)
	}
}

func TestSettingsGet(t *testing.T) {
	capUSD := money.MustParse("25.50")
	code, body := get(t, server(t, withReads(&reads{cap: &capUSD}, nil)), "/v1/workspaces/acme/settings")
	if code != http.StatusOK || body != `{"monthly_cap_usd":"25.50"}` {
		t.Fatalf("got %d %s", code, body)
	}
	code, body = get(t, server(t, withReads(&reads{}, nil)), "/v1/workspaces/acme/settings")
	if code != http.StatusOK || body != `{"monthly_cap_usd":null}` {
		t.Fatalf("got %d %s", code, body)
	}
}

func TestSettingsPut(t *testing.T) {
	r := &reads{}
	srv := server(t, withReads(r, nil))
	url := srv.URL + "/v1/workspaces/acme/settings"
	cases := []struct{ body, want string }{
		{`{"monthly_cap_usd":"100.5"}`, `{"monthly_cap_usd":"100.5"}`},
		{`{"monthly_cap_usd":12}`, `{"monthly_cap_usd":"12"}`},
		{`{"monthly_cap_usd":null}`, `{"monthly_cap_usd":null}`},
	}
	for _, c := range cases {
		if code, body := put(t, url, "application/json", c.body); code != http.StatusOK || body != c.want {
			t.Fatalf("%s: got %d %s", c.body, code, body)
		}
	}
	if len(r.set) != 3 || r.set[0].String() != "100.5" || r.set[2] != nil {
		t.Fatalf("writes %v", r.set)
	}
	refusals := map[string]string{
		``:                           `"type":"missing","loc":["body"]`,
		`{}`:                         `"type":"missing","loc":["body","monthly_cap_usd"]`,
		`[]`:                         `"type":"model_attributes_type"`,
		`{"monthly_cap_usd":"-1"}`:   `"type":"greater_than_equal","loc":["body","monthly_cap_usd"]`,
		`{"monthly_cap_usd":"lots"}`: `"msg":"Value error, 'lots' is not a money amount"`,
	}
	for in, want := range refusals {
		if code, body := put(t, url, "application/json", in); code != http.StatusUnprocessableEntity || !strings.Contains(body, want) {
			t.Fatalf("%q: got %d %s", in, code, body)
		}
	}
	if len(r.set) != 3 {
		t.Fatal("a refused body was written")
	}
}

func TestSettingsPutRefusedCapIs422(t *testing.T) {
	r := &reads{capErr: &governanceapi.CapRefused{Detail: "cap is not enforceable"}}
	srv := server(t, withReads(r, nil))
	code, body := put(t, srv.URL+"/v1/workspaces/acme/settings", "application/json", `{"monthly_cap_usd":"1"}`)
	if code != http.StatusUnprocessableEntity || !strings.Contains(body, `"detail":"cap is not enforceable"`) {
		t.Fatalf("got %d %s", code, body)
	}
}

func TestSettingsPutNonAdminIs403BeforeTheBody(t *testing.T) {
	r := &reads{}
	srv := server(t, withReads(r, authz.ErrNotWorkspaceAdmin))
	code, _ := put(t, srv.URL+"/v1/workspaces/acme/settings", "application/json", `not json`)
	if code != http.StatusForbidden || len(r.set) != 0 {
		t.Fatalf("got %d, writes %v", code, r.set)
	}
}

func TestPeopleAccessNonAdminIs403(t *testing.T) {
	code, _ := get(t, server(t, withReads(&reads{}, authz.ErrNotWorkspaceAdmin)), "/v1/workspaces/acme/network/people-access")
	if code != http.StatusForbidden {
		t.Fatalf("got %d", code)
	}
}

func TestTopologyBody(t *testing.T) {
	code, body := get(t, server(t, withReads(&reads{}, nil)), "/v1/workspaces/acme/network/topology")
	want := `{"nodes":[{"id":"a1","type":"agent","label":"Scout","status":"active","metadata":{}},` +
		`{"id":"t1","type":"trigger","label":"Daily","status":"active","metadata":{"trigger_type":"cron"}}],` +
		`"edges":[{"id":"a1-t1-has_trigger","source":"a1","target":"t1","relation":"has_trigger"}],"governance":[],"deployment_mode":"oss"}`
	if code != http.StatusOK || body != want {
		t.Fatalf("got %d %s", code, body)
	}
}

func TestDashboardFieldOrder(t *testing.T) {
	at := time.Date(2026, 11, 15, 9, 30, 0, 120000, time.UTC)
	name := "Scout"
	pct := 12.5
	d := service.Dashboard{
		Spend:       service.SpendCard{Today: money.MustParse("1"), MTD: money.MustParse("5"), PctOfCap: &pct, ProjectedEOM: money.MustParse("9.00"), MTDEstimateUSD: money.Zero()},
		ActiveTasks: []service.DashboardTask{{TaskID: "t1", AgentID: "a1", AgentName: &name, Title: "crawl", Status: "running", StartedAt: &at}},
		Schedule:    service.Schedule{HorizonDays: 42},
	}
	raw, err := wirejson.Marshal(dashboardJSON(d), wirejson.Compact)
	if err != nil {
		t.Fatal(err)
	}
	want := `{"spend":{"today_usd":"1","mtd_usd":"5","cap_usd":null,"pct_of_cap":12.5,"projected_eom_usd":"9.00","projection_method":"trailing-7d","not_covered":[],"mtd_estimate_usd":"0"},` +
		`"blockers":{"hitl":[],"awaiting_continuation":[],"blocked_24h":[],"wallet_exhausted":[],"failed_24h":[]},` +
		`"active_tasks":[{"task_id":"t1","agent_id":"a1","agent_name":"Scout","title":"crawl","status":"running","started_at":"2026-11-15T09:30:00.000120Z","finished_at":null,"cost_usd":null}],` +
		`"recent_tasks":[],"schedule":{"horizon_days":42,"runs":[],"frequent":[]},"daily_spend":[],"top_agents":[],"health":{"connections":[],"triggers":[]},"usage":null}`
	if string(raw) != want {
		t.Fatalf("got  %s\nwant %s", raw, want)
	}
}
