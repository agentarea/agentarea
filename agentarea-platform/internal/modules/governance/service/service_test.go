package service

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/store"
)

type fakeDB struct{ db.Database }

func (fakeDB) Read(_ context.Context, ws scope.Workspace) (db.Session, func(), error) {
	return db.NewSession(ws, nil), func() {}, nil
}

func (fakeDB) Write(ctx context.Context, ws scope.Workspace, fn func(context.Context, db.Session) error) error {
	return fn(ctx, db.NewTxSession(ws, nil))
}

type fakePolicies struct {
	rows  []domain.Rule
	by    map[string]string
	fails error
}

func match(p *string, v string) bool { return p == nil || *p == v }

func (f *fakePolicies) List(_ context.Context, _ db.Session, q store.Filter) ([]domain.Rule, error) {
	var out []domain.Rule
	for _, r := range f.rows {
		if match(q.SubjectType, r.SubjectType) && match(q.SubjectID, r.SubjectID) && match(q.Effect, r.Effect) &&
			match(q.Target, r.Target) && (q.Enabled == nil || *q.Enabled == r.Enabled) {
			out = append(out, r)
		}
	}
	return out, nil
}

func (f *fakePolicies) Get(_ context.Context, _ db.Session, id uuid.UUID) (domain.Rule, bool, error) {
	for _, r := range f.rows {
		if r.ID == id.String() {
			return r, true, nil
		}
	}
	return domain.Rule{}, false, nil
}

func (f *fakePolicies) Create(_ context.Context, _ db.Session, id uuid.UUID, by string, r domain.Rule, _ time.Time) (domain.Rule, error) {
	if f.fails != nil {
		return domain.Rule{}, f.fails
	}
	r.ID = id.String()
	f.rows = append(f.rows, r)
	if f.by == nil {
		f.by = map[string]string{}
	}
	f.by[r.ID] = by
	return r, nil
}

func (f *fakePolicies) Update(_ context.Context, _ db.Session, id uuid.UUID, p store.Patch, _ time.Time) (domain.Rule, bool, error) {
	for i, r := range f.rows {
		if r.ID != id.String() {
			continue
		}
		if p.Target != nil {
			r.Target = *p.Target
		}
		if p.Params != nil {
			r.Params = p.Params
		}
		if p.Enabled != nil {
			r.Enabled = *p.Enabled
		}
		f.rows[i] = r
		return r, true, nil
	}
	return domain.Rule{}, false, nil
}

func (f *fakePolicies) Delete(_ context.Context, _ db.Session, id uuid.UUID) (bool, error) {
	for i, r := range f.rows {
		if r.ID == id.String() {
			f.rows = append(f.rows[:i], f.rows[i+1:]...)
			return true, nil
		}
	}
	return false, nil
}

type fakeAudit struct {
	events []domain.AuditEvent
	fails  error
	seen   map[string]bool
}

func (f *fakeAudit) Insert(_ context.Context, _ db.Querier, e domain.AuditEvent, _ time.Time) error {
	if f.fails != nil {
		return f.fails
	}
	f.events = append(f.events, e)
	return nil
}

func (f *fakeAudit) InsertOnce(_ context.Context, _ db.Querier, e domain.AuditEvent) (bool, error) {
	if f.seen == nil {
		f.seen = map[string]bool{}
	}
	if f.seen[e.ID] {
		return false, nil
	}
	f.seen[e.ID] = true
	f.events = append(f.events, e)
	return true, nil
}

func (f *fakeAudit) Query(context.Context, db.Session, domain.AuditQuery) ([]domain.AuditEvent, error) {
	return f.events, nil
}

func (f *fakeAudit) ResourcePage(context.Context, db.Session, string, []string, int, int) ([]domain.AuditEvent, int64, error) {
	return f.events, int64(len(f.events)), nil
}

type fixture struct {
	sv     *Service
	rules  *fakePolicies
	audit  *fakeAudit
	caller authn.Caller
	ws     scope.Workspace
}

func newFixture(t *testing.T) fixture {
	t.Helper()
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	f := fixture{rules: &fakePolicies{}, audit: &fakeAudit{}, ws: ws,
		caller: authn.Caller{Principal: authn.Principal{UserID: "owner"}, Workspace: ws}}
	f.sv = New(Deps{DB: fakeDB{}, Policies: f.rules, Audit: f.audit, Log: slog.New(slog.NewTextHandler(io.Discard, nil))})
	return f
}

func obj(kv ...any) wirejson.Object {
	o := wirejson.Object{}
	for i := 0; i+1 < len(kv); i += 2 {
		o.Set(kv[i].(string), kv[i+1])
	}
	return o
}

func wsRule(ws scope.Workspace, target, effect string, params wirejson.Object) domain.Rule {
	return domain.Rule{SubjectType: "workspace", SubjectID: ws.ID(), Target: target, Effect: effect, Enabled: true, Params: params}
}

func TestCreateRuleRefusesUnenforceableAndAudits(t *testing.T) {
	f := newFixture(t)
	ctx := context.Background()
	if _, err := f.sv.CreateRule(ctx, f.caller, wsRule(f.ws, "tool:*", "deny", obj())); !errors.Is(err, domain.ErrNotEnforceable) {
		t.Fatalf("wildcard deny accepted: %v", err)
	}
	if len(f.rules.rows) != 0 || len(f.audit.events) != 0 {
		t.Fatal("refused rule was written")
	}
	r, err := f.sv.CreateRule(ctx, f.caller, wsRule(f.ws, "tool:rm", "deny", obj()))
	if err != nil {
		t.Fatal(err)
	}
	if f.rules.by[r.ID] != "owner" {
		t.Fatalf("created_by %q", f.rules.by[r.ID])
	}
	e := f.audit.events[0]
	if e.Action != "governance_policy.create" || e.ResourceType != "governance_policy" || *e.ResourceID != r.ID || e.ActorID != "owner" || e.Changes != nil {
		t.Fatalf("audit %+v", e)
	}
}

func TestPolicyAuditFailureIsSwallowed(t *testing.T) {
	f := newFixture(t)
	f.audit.fails = errors.New("audit down")
	if _, err := f.sv.CreateRule(context.Background(), f.caller, wsRule(f.ws, "tool:rm", "deny", obj())); err != nil {
		t.Fatalf("@audited raised: %v", err)
	}
}

func TestUpdateAndDeleteRule(t *testing.T) {
	f := newFixture(t)
	ctx := context.Background()
	r, _ := f.sv.CreateRule(ctx, f.caller, wsRule(f.ws, "tool:rm", "deny", obj()))
	id := uuid.MustParse(r.ID)
	star := "tool:*"
	_, err := f.sv.UpdateRule(ctx, f.caller, id, func(x domain.Rule) domain.Rule { x.Target = star; return x }, RulePatch{Target: &star})
	if !errors.Is(err, domain.ErrNotEnforceable) {
		t.Fatalf("patch to a wildcard accepted: %v", err)
	}
	other := "tool:mv"
	got, err := f.sv.UpdateRule(ctx, f.caller, id, func(x domain.Rule) domain.Rule { x.Target = other; return x }, RulePatch{Target: &other})
	if err != nil || got.Target != other {
		t.Fatalf("got %+v %v", got, err)
	}
	if _, err := f.sv.UpdateRule(ctx, f.caller, uuid.New(), func(x domain.Rule) domain.Rule { return x }, RulePatch{}); !errors.Is(err, ErrRuleNotFound) {
		t.Fatalf("missing rule: %v", err)
	}
	if err := f.sv.DeleteRule(ctx, f.caller, id); err != nil {
		t.Fatal(err)
	}
	if err := f.sv.DeleteRule(ctx, f.caller, id); !errors.Is(err, ErrRuleNotFound) || err.Error() != "Policy rule not found" {
		t.Fatalf("second delete: %v", err)
	}
	actions := []string{}
	for _, e := range f.audit.events {
		actions = append(actions, e.Action)
	}
	if len(actions) != 3 || actions[1] != "governance_policy.update" || actions[2] != "governance_policy.delete" {
		t.Fatalf("audit trail %v", actions)
	}
}

func TestListAndGetSkipUnknownKinds(t *testing.T) {
	f := newFixture(t)
	odd := wsRule(f.ws, "tool:x", "throttle", obj())
	odd.ID = uuid.NewString()
	f.rules.rows = append(f.rules.rows, odd)
	rules, err := f.sv.ListRules(context.Background(), f.caller, Filter{})
	if err != nil || len(rules) != 0 {
		t.Fatalf("got %v %v", rules, err)
	}
	if _, err := f.sv.GetRule(context.Background(), f.caller, uuid.MustParse(odd.ID)); !errors.Is(err, ErrRuleNotFound) {
		t.Fatalf("got %v", err)
	}
}

func TestResolveLayersWorkspaceAgentUser(t *testing.T) {
	f := newFixture(t)
	ctx := context.Background()
	add := func(r domain.Rule) {
		if _, err := f.sv.CreateRule(ctx, f.caller, r); err != nil {
			t.Fatal(err)
		}
	}
	add(wsRule(f.ws, "spend", "cap", obj("amount_usd", "50", "period", "run")))
	agent := wsRule(f.ws, "spend", "cap", obj("amount_usd", "20", "period", "run"))
	agent.SubjectType, agent.SubjectID = "agent", "a1"
	add(agent)
	user := wsRule(f.ws, "tool:rm", "deny", obj())
	user.SubjectType, user.SubjectID = "user", "u1"
	add(user)

	p, err := f.sv.Resolve(ctx, api.RunPrincipal{Workspace: f.ws, AgentID: "a1", UserID: "u1"}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if p.Budget.RunBudgetUSD.String() != "20" || p.Tools == nil || p.Tools.Denied[0] != "rm" || len(p.SourcePolicyIDs) != 3 {
		t.Fatalf("got %+v", p)
	}
	preview, err := f.sv.Preview(ctx, f.ws, "a1", nil)
	if err != nil || preview.Tools != nil {
		t.Fatalf("preview has the user layer: %+v %v", preview, err)
	}
	loose, _ := money.Parse("30")
	if _, err := f.sv.Preview(ctx, f.ws, "a1", &api.Policy{Budget: &api.Budget{RunBudgetUSD: &loose}}); !errors.Is(err, api.ErrPolicyRefused) {
		t.Fatalf("task policy loosened the agent cap: %v", err)
	}
	b, err := f.sv.CurrentBudget(ctx, api.RunPrincipal{Workspace: f.ws})
	if err != nil || b.RunBudgetUSD.String() != "50" {
		t.Fatalf("budget %+v %v", b, err)
	}
}

func TestProvisionDefaultsIsIdempotent(t *testing.T) {
	f := newFixture(t)
	ctx := context.Background()
	if err := f.sv.ProvisionDefaults(ctx, nil, f.ws, "creator"); err != nil {
		t.Fatal(err)
	}
	n := len(f.rules.rows)
	if n == 0 || len(f.audit.events) != n {
		t.Fatalf("seeded %d rules, %d audit rows", n, len(f.audit.events))
	}
	for _, r := range f.rules.rows {
		if r.SubjectType != "workspace" || r.SubjectID != f.ws.ID() || f.rules.by[r.ID] != "creator" {
			t.Fatalf("rule %+v by %q", r, f.rules.by[r.ID])
		}
	}
	if err := f.sv.ProvisionDefaults(ctx, nil, f.ws, "creator"); err != nil {
		t.Fatal(err)
	}
	if len(f.rules.rows) != n {
		t.Fatalf("second run added %d rules", len(f.rules.rows)-n)
	}
	p, err := f.sv.Resolve(ctx, api.RunPrincipal{Workspace: f.ws}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if err := p.RequireRuntimeContract(); err != nil {
		t.Fatalf("baseline does not satisfy the runtime contract: %v", err)
	}
	if p.Budget.MonthlySpendCapUSD.Cmp(mustMoney(t, "500")) != 0 || p.Budget.RunBudgetUSD.Cmp(mustMoney(t, "50")) != 0 {
		t.Fatalf("budget %+v", p.Budget)
	}
}

func TestDefaultPoliciesPathMustExist(t *testing.T) {
	f := newFixture(t)
	f.sv.d.DefaultPoliciesPath = filepath.Join(t.TempDir(), "missing.yaml")
	if err := f.sv.ProvisionDefaults(context.Background(), nil, f.ws, "c"); err == nil {
		t.Fatal("a missing baseline file seeded nothing silently")
	}
	path := filepath.Join(t.TempDir(), "p.yaml")
	if err := os.WriteFile(path, []byte("policies:\n  - target: tool:rm\n    effect: deny\n    priority: 3\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	f.sv.d.DefaultPoliciesPath = path
	if err := f.sv.ProvisionDefaults(context.Background(), nil, f.ws, "c"); err != nil {
		t.Fatal(err)
	}
	if len(f.rules.rows) != 1 || f.rules.rows[0].Priority != 3 {
		t.Fatalf("rows %+v", f.rules.rows)
	}
}

func TestDelegationBoundedByParent(t *testing.T) {
	f := newFixture(t)
	ctx := context.Background()
	if err := f.sv.ProvisionDefaults(ctx, nil, f.ws, "creator"); err != nil {
		t.Fatal(err)
	}
	parent, err := f.sv.Resolve(ctx, api.RunPrincipal{Workspace: f.ws}, nil)
	if err != nil {
		t.Fatal(err)
	}
	pol, snap, err := f.sv.Delegation(ctx, api.RunPrincipal{Workspace: f.ws, UserID: "u"}, api.DelegationRequest{TargetAgentID: "researcher", UpperBound: parent, RunBudget: mustMoney(t, "5")})
	if err != nil {
		t.Fatal(err)
	}
	if pol.Budget.RunBudgetUSD.String() != "5" || snap.Revision != 1 || len(snap.LimitCeilings) == 0 {
		t.Fatalf("got %+v %+v", pol.Budget, snap)
	}
	if _, _, err := f.sv.Delegation(ctx, api.RunPrincipal{Workspace: f.ws}, api.DelegationRequest{TargetAgentID: "researcher", UpperBound: parent, RunBudget: mustMoney(t, "0")}); err == nil {
		t.Fatal("zero run budget delegated")
	}
	tight := parent
	b := *parent.Budget
	one := mustMoney(t, "1")
	b.RunBudgetUSD = &one
	tight.Budget = &b
	if _, _, err := f.sv.Delegation(ctx, api.RunPrincipal{Workspace: f.ws}, api.DelegationRequest{TargetAgentID: "researcher", UpperBound: tight, RunBudget: mustMoney(t, "5")}); !errors.Is(err, api.ErrPolicyRefused) {
		t.Fatalf("child looser than parent: %v", err)
	}
}

func TestDelegationInheritsTighterParentLimits(t *testing.T) {
	f := newFixture(t)
	ctx := context.Background()
	if err := f.sv.ProvisionDefaults(ctx, nil, f.ws, "creator"); err != nil {
		t.Fatal(err)
	}
	turns := int64(24)
	coordinator := api.RunPrincipal{Workspace: f.ws, UserID: "u", AgentID: "coordinator"}
	parent, err := f.sv.Resolve(ctx, coordinator, &api.Policy{Execution: &api.Execution{MaxModelTurns: &turns}})
	if err != nil {
		t.Fatal(err)
	}
	pol, snap, err := f.sv.Delegation(ctx, coordinator, api.DelegationRequest{TargetAgentID: "researcher", UpperBound: parent, RunBudget: mustMoney(t, "5")})
	if err != nil {
		t.Fatalf("a delegate under a tighter parent was refused: %v", err)
	}
	if *pol.Execution.MaxModelTurns != 24 || *snap.EffectivePolicy.Execution.MaxModelTurns != 24 {
		t.Fatalf("child turns %d, want the parent's 24", *pol.Execution.MaxModelTurns)
	}
	f.rules.rows = append(f.rules.rows, domain.Rule{SubjectType: "agent", SubjectID: "researcher", Target: "execution", Effect: "cap", Enabled: true,
		Params: obj("max_model_turns", json.Number("10"))})
	pol, _, err = f.sv.Delegation(ctx, coordinator, api.DelegationRequest{TargetAgentID: "researcher", UpperBound: parent, RunBudget: mustMoney(t, "5")})
	if err != nil {
		t.Fatal(err)
	}
	if *pol.Execution.MaxModelTurns != 10 {
		t.Fatalf("child turns %d, want the delegate's own 10", *pol.Execution.MaxModelTurns)
	}
}

func TestRecordOnceWritesOnce(t *testing.T) {
	f := newFixture(t)
	tx := db.NewTxSession(f.ws, nil)
	rec := api.AuditRecord{EventID: uuid.NewString(), Action: "task.cancel", ResourceType: "task", ResourceID: "t1", ActorID: "u"}
	for range 2 {
		if err := f.sv.RecordOnce(context.Background(), tx, rec); err != nil {
			t.Fatal(err)
		}
	}
	if len(f.audit.events) != 1 || f.audit.events[0].ActorType != "user" {
		t.Fatalf("events %+v", f.audit.events)
	}
	if err := f.sv.RecordOnce(context.Background(), tx, api.AuditRecord{EventID: uuid.NewString()}); err == nil {
		t.Fatal("record without actor accepted")
	}
}

func TestTaskMergesTheCallersRequests(t *testing.T) {
	f := newFixture(t)
	ctx := context.Background()
	if err := f.sv.ProvisionDefaults(ctx, nil, f.ws, "creator"); err != nil {
		t.Fatal(err)
	}
	p := api.RunPrincipal{Workspace: f.ws, UserID: "u"}
	pol, snap, err := f.sv.Task(ctx, p, api.TaskRequest{})
	if err != nil {
		t.Fatal(err)
	}
	if *pol.Execution.MaxModelTurns != 100 || snap.RequestedExecution != nil || len(snap.RequestedPolicy.DocumentStored()) != 0 || snap.Revision != 1 {
		t.Fatalf("plain run: %+v %+v", pol.Execution, snap)
	}
	turns := int64(7)
	pol, snap, err = f.sv.Task(ctx, p, api.TaskRequest{ExecutionTurns: &turns, MaxIterations: json.Number("7"), RequiresHumanApproval: true})
	if err != nil {
		t.Fatal(err)
	}
	if *pol.Execution.MaxModelTurns != 7 || *snap.RequestedExecution.MaxModelTurns != 7 || !*pol.Approval.RequiresHumanApproval {
		t.Fatalf("requested: %+v %+v", pol, snap)
	}
	if len(snap.LimitCeilings) == 0 || snap.LimitCeilings[0].Value != "100" {
		t.Fatalf("ceilings come from the layers alone: %+v", snap.LimitCeilings)
	}
	for name, req := range map[string]api.TaskRequest{
		"execution.max_model_turns conflicts with parameters.max_iterations": {ExecutionTurns: &turns, MaxIterations: json.Number("8")},
		"parameters.max_iterations must be a positive integer":               {MaxIterations: wirejson.Float(7)},
		"max_model_turns cannot loosen higher-scope ceiling":                 {MaxIterations: json.Number("500")},
	} {
		if _, _, err := f.sv.Task(ctx, p, req); !errors.Is(err, api.ErrPolicyRefused) || err.Error() != name {
			t.Fatalf("%s: %v", name, err)
		}
	}
	one := int64(1)
	if _, _, err := f.sv.Task(ctx, p, api.TaskRequest{ExecutionTurns: &one, MaxIterations: true}); err == nil || err.Error() != "parameters.max_iterations must be a positive integer" {
		t.Fatalf("True equals 1 but is no int: %v", err)
	}
}
