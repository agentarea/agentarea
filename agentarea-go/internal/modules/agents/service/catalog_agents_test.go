package service

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"strings"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
)

type fakeApprovals struct {
	synced   map[string][]string
	released [][]string
}

func (f *fakeApprovals) Targets(context.Context, scope.Workspace, []string) (map[string][]string, error) {
	return map[string][]string{}, nil
}

func (f *fakeApprovals) Sync(_ context.Context, _ db.Session, _ authn.Caller, agentID string, targets []string) error {
	f.synced[agentID] = targets
	return nil
}

func (f *fakeApprovals) Release(_ context.Context, _ db.Session, _ authn.Caller, _ string, unticked []string) error {
	f.released = append(f.released, unticked)
	return nil
}

type fakeTriggers struct{ fail error }

func (fakeTriggers) Check(context.Context, authn.Caller, []json.RawMessage) error { return nil }

func (f fakeTriggers) Create(context.Context, authn.Caller, string, []json.RawMessage) error {
	return f.fail
}

type agentFakeItems struct {
	CatalogItems
	agents, skills map[string]catalogapi.CatalogItem
	presets        []catalogapi.CatalogItem
	marked         []string
}

func (f *agentFakeItems) AgentPresets(context.Context, scope.Workspace) ([]catalogapi.CatalogItem, error) {
	return f.presets, nil
}

func (f *agentFakeItems) AgentItem(_ context.Context, _ scope.Workspace, id string) (catalogapi.CatalogItem, bool, error) {
	it, ok := f.agents[id]
	return it, ok, nil
}

func (f *agentFakeItems) AgentItems(context.Context, scope.Workspace) ([]catalogapi.CatalogItem, error) {
	var out []catalogapi.CatalogItem
	for _, it := range f.agents {
		out = append(out, it)
	}
	return out, nil
}

func (f *agentFakeItems) SkillByKey(_ context.Context, _ scope.Workspace, key string) (catalogapi.CatalogItem, bool, error) {
	it, ok := f.skills[key]
	return it, ok, nil
}

func (f *agentFakeItems) MarkInstalled(_ context.Context, _ db.Session, itemID, entityID string, _ *string) error {
	f.marked = append(f.marked, itemID+"="+entityID)
	return nil
}

func agentItem(name string, spec string) catalogapi.CatalogItem {
	v := "3"
	return catalogapi.CatalogItem{ID: uuid.NewString(), Name: name, Version: &v, Spec: json.RawMessage(spec), RegistryID: "reg", RegistryTrust: "verified"}
}

func TestCreateWithTriggersRollsBackWhenOneFails(t *testing.T) {
	d, _, s, c := clientSetup(t)
	appr := &fakeApprovals{synced: map[string][]string{}}
	s.UseApprovals(appr)
	s.d.Triggers = fakeTriggers{fail: errors.New("Trigger 'nightly': bad cron")}
	confirm := true
	in := Create{Name: "Triggered", AgentType: "standard", Triggers: []json.RawMessage{json.RawMessage(`{"name":"nightly"}`)},
		Tools: []domain.Tool{{Type: domain.ToolCode, Name: "agentarea/files", Settings: &domain.Settings{RequiresUserConfirmation: &confirm}}}}
	if _, err := s.Create(context.Background(), c, in); err == nil || !strings.Contains(err.Error(), "bad cron") {
		t.Fatalf("want the trigger refusal, got %v", err)
	}
	if got := createAgents(t, s, d, c); len(got) != 0 {
		t.Fatalf("a failed trigger left %d agents", len(got))
	}
	for id, targets := range appr.synced {
		if len(targets) != 0 {
			t.Fatalf("the rollback left approval rules on %s: %v", id, targets)
		}
	}

	s.d.Triggers = fakeTriggers{}
	v, err := s.Create(context.Background(), c, in)
	if err != nil {
		t.Fatal(err)
	}
	if got := appr.synced[v.Agent.ID]; !reflect.DeepEqual(got, []string{"tool:files"}) {
		t.Fatalf("approval targets: %v", got)
	}
}

func TestUntickedTargets(t *testing.T) {
	no, yes := false, true
	got := untickedTargets([]domain.Tool{
		{Type: domain.ToolCode, Name: "agentarea/shell", Settings: &domain.Settings{RequiresUserConfirmation: &no}},
		{Type: domain.ToolCode, Name: "agentarea/files", Settings: &domain.Settings{RequiresUserConfirmation: &yes}},
		{Type: domain.ToolMCP, Name: "srv", Settings: &domain.Settings{MCPAllowed: &[]domain.MCPPermission{
			{ToolName: "read"}, {ToolName: "write", RequiresUserConfirmation: &yes}}}},
	})
	if want := []string{"tool:mcp:srv:read", "tool:read", "tool:shell"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestPresetsResolveSkillKeys(t *testing.T) {
	_, _, s, c := clientSetup(t)
	desc := "Searches"
	skill := catalogapi.CatalogItem{ID: uuid.NewString(), Name: "web-search", Description: &desc}
	items := &agentFakeItems{skills: map[string]catalogapi.CatalogItem{"web-search": skill},
		presets: []catalogapi.CatalogItem{agentItem("Researcher",
			`{"instruction":"Find things","tools":[{"type":"code","name":"agentarea/files"}],"skills":["web-search","gone"],"triggers":[{"name":"t"}]}`)}}
	body, err := CatalogAgents{S: s, Items: items}.PresetsJSON(context.Background(), c)
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(body)
	for _, want := range []string{`"instruction":"Find things"`, `"preferred_models":[]`, `"name":"agentarea/files"`,
		`"skills":[{"id":"` + skill.ID + `","name":"web-search","description":"Searches"}]`, `"unavailable_skills":["gone"]`, `"triggers":[{"name":"t"}]`} {
		if !strings.Contains(string(raw), want) {
			t.Fatalf("%s lacks %s", raw, want)
		}
	}

	items.presets = []catalogapi.CatalogItem{agentItem("Broken", `{"tools":[{"type":"nope"}]}`)}
	var bad *PresetMalformedError
	if _, err := (CatalogAgents{S: s, Items: items}).PresetsJSON(context.Background(), c); !errors.As(err, &bad) {
		t.Fatalf("malformed preset: %v", err)
	}
}

func TestInstallForksACatalogAgentOnce(t *testing.T) {
	ctx := context.Background()
	d, _, s, c := clientSetup(t)
	appr := &fakeApprovals{synced: map[string][]string{}}
	s.UseApprovals(appr)
	item := agentItem("Release Helper", `{"instruction":"Ship","planning":true,"tools":[{"type":"code","name":"agentarea/shell","settings":{"requires_user_confirmation":true}}]}`)
	items := &agentFakeItems{agents: map[string]catalogapi.CatalogItem{item.ID: item}}
	x := CatalogAgents{S: s, Items: items, Policy: runFakePolicy{}}

	id, err := x.Install(ctx, c, "release-helper")
	if err != nil {
		t.Fatal(err)
	}
	a, ok, err := s.load(ctx, c.Workspace, uuid.MustParse(id), false)
	if err != nil || !ok {
		t.Fatalf("fork not stored: %v", err)
	}
	if a.RegistryItemID == nil || *a.RegistryItemID != item.ID || a.ModelID != nil || a.Instruction == nil || *a.Instruction != "Ship" ||
		a.Planning == nil || !*a.Planning || strings.Contains(string(a.Tools), "requires_user_confirmation") {
		t.Fatalf("fork: %+v tools %s", a, a.Tools)
	}
	if !reflect.DeepEqual(appr.synced[id], []string{"tool:shell"}) || len(items.marked) != 1 {
		t.Fatalf("approvals %v, marks %v", appr.synced, items.marked)
	}

	if err := s.setStatus(ctx, c, uuid.MustParse(id), domain.StatusActive, domain.StatusArchived, "agent.archive"); err != nil {
		t.Fatal(err)
	}
	again, err := x.Install(ctx, c, item.ID)
	if err != nil || again != id || len(items.marked) != 1 {
		t.Fatalf("second install: %v %s vs %s", err, again, id)
	}
	if a, _, _ := s.load(ctx, c.Workspace, uuid.MustParse(id), false); a.Status != domain.StatusActive {
		t.Fatalf("an archived fork stays %s", a.Status)
	}
	if got := createAgents(t, s, d, c); len(got) != 1 {
		t.Fatalf("%d agents", len(got))
	}
	if _, err := x.Install(ctx, c, uuid.NewString()); !errors.Is(err, domain.ErrAgentNotFound) {
		t.Fatalf("unknown id: %v", err)
	}
}

func TestInstallOfACatalogAgentAsksThePolicy(t *testing.T) {
	_, _, s, c := clientSetup(t)
	item := agentItem("Blocked", `{"tools":[]}`)
	x := CatalogAgents{S: s, Items: &agentFakeItems{agents: map[string]catalogapi.CatalogItem{item.ID: item}}, Policy: installRefusingPolicy{}}
	if _, err := x.Install(context.Background(), c, item.ID); err == nil || err.Error() != "refused" {
		t.Fatalf("want the refusal, got %v", err)
	}
}

type relationGraph struct {
	*clientFakeGraph
	denied map[string]bool
}

func (g relationGraph) Check(ctx context.Context, subject, relation, typ, id string) (bool, error) {
	if g.denied[relation+" "+id] {
		return false, nil
	}
	return g.clientFakeGraph.Check(ctx, subject, relation, typ, id)
}

func TestInstallByAnAgentsIDOrSlugChecksTheGraph(t *testing.T) {
	ctx := context.Background()
	_, g, s, c := clientSetup(t)
	v, err := s.Create(ctx, c, Create{Name: "Private Helper", AgentType: "standard"})
	if err != nil {
		t.Fatal(err)
	}
	id := v.Agent.ID
	rg := relationGraph{clientFakeGraph: g, denied: map[string]bool{}}
	s.d.Graph = rg
	x := CatalogAgents{S: s, Items: &agentFakeItems{}}

	rg.denied[authz.CanRead+" "+id] = true
	for _, ident := range []string{id, v.Agent.Slug} {
		if _, err := x.Install(ctx, c, ident); !errors.Is(err, ErrDenied) {
			t.Fatalf("install of an unreadable agent by %q: %v", ident, err)
		}
	}
	delete(rg.denied, authz.CanRead+" "+id)

	if err := s.setStatus(ctx, c, uuid.MustParse(id), domain.StatusActive, domain.StatusArchived, "agent.archive"); err != nil {
		t.Fatal(err)
	}
	rg.denied[authz.CanManage+" "+id] = true
	if _, err := x.Install(ctx, c, id); !errors.Is(err, ErrDenied) {
		t.Fatalf("restore without delete: %v", err)
	}
	if a, _, _ := s.load(ctx, c.Workspace, uuid.MustParse(id), false); a.Status != domain.StatusArchived {
		t.Fatalf("a refused install restored the agent: %s", a.Status)
	}
	delete(rg.denied, authz.CanManage+" "+id)
	if got, err := x.Install(ctx, c, id); err != nil || got != id {
		t.Fatalf("install by its owner: %v %s", err, got)
	}
}

func TestUpdateReleasesApprovalsOnlyAfterValidation(t *testing.T) {
	ctx := context.Background()
	_, _, s, c := clientSetup(t)
	appr := &fakeApprovals{synced: map[string][]string{}}
	s.UseApprovals(appr)
	yes, no := true, false
	v, err := s.Create(ctx, c, Create{Name: "Gated", AgentType: "standard",
		Tools: []domain.Tool{{Type: domain.ToolCode, Name: "agentarea/shell", Settings: &domain.Settings{RequiresUserConfirmation: &yes}}}})
	if err != nil {
		t.Fatal(err)
	}
	unticked := []domain.Tool{{Type: domain.ToolCode, Name: "agentarea/shell", Settings: &domain.Settings{RequiresUserConfirmation: &no}}}
	bad := "not-a-model"
	_, err = s.Update(ctx, c, v.Agent.ID, Patch{Tools: &unticked, ModelID: Set[string]{Set: true, Value: &bad}})
	var inv *domain.InvalidError
	if !errors.As(err, &inv) {
		t.Fatalf("want the model refusal, got %v", err)
	}
	if len(appr.released) != 0 {
		t.Fatalf("a refused PATCH released approval rules: %v", appr.released)
	}
}

type cancellingTriggers struct{ cancel context.CancelFunc }

func (cancellingTriggers) Check(context.Context, authn.Caller, []json.RawMessage) error { return nil }

func (f cancellingTriggers) Create(context.Context, authn.Caller, string, []json.RawMessage) error {
	f.cancel()
	return errors.New("Trigger 'nightly': bad cron")
}

func TestCreateRollsBackTriggersAfterTheClientLeft(t *testing.T) {
	d, _, s, c := clientSetup(t)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	s.d.Triggers = cancellingTriggers{cancel: cancel}
	in := Create{Name: "Left", AgentType: "standard", Triggers: []json.RawMessage{json.RawMessage(`{"name":"nightly"}`)}}
	if _, err := s.Create(ctx, c, in); err == nil || !strings.Contains(err.Error(), "bad cron") || strings.Contains(err.Error(), "context canceled") {
		t.Fatalf("want only the trigger refusal, got %v", err)
	}
	if got := createAgents(t, s, d, c); len(got) != 0 {
		t.Fatalf("a disconnected client left %d agents", len(got))
	}
}

func TestCatalogPackageRefusesAMirrorThatLeavesItsArea(t *testing.T) {
	for _, s3 := range []string{"skills/catalog/../ws2/packages/abc", `skills/catalog/x\..\abc`} {
		_, err := (&Skills{}).catalogPackage(context.Background(), map[string]any{"package": map[string]any{"s3_path": s3}}, nil, "")
		var v *domain.SkillValueError
		if !errors.As(err, &v) {
			t.Fatalf("%s: %v", s3, err)
		}
	}
}
