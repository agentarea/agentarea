package authz

import (
	"context"
	"errors"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// memGraph stores tuples and answers checks by direct tuple only; writes
// fail the way OpenFGA does on a duplicate write or a missing delete.
type memGraph struct {
	tuples map[Tuple]bool
	writes int
	fail   error
}

func newMem() *memGraph { return &memGraph{tuples: map[Tuple]bool{}} }

func (m *memGraph) Check(_ context.Context, subject, relation, objectType, objectID string) (bool, error) {
	return m.tuples[Tuple{User: subject, Relation: relation, Object: ObjectRef(objectType, objectID)}], nil
}

func (m *memGraph) BatchCheck(ctx context.Context, items []CheckItem) ([]bool, error) {
	out := make([]bool, len(items))
	for i, it := range items {
		out[i], _ = m.Check(ctx, it.Subject, it.Relation, it.ObjectType, it.ObjectID)
	}
	return out, nil
}

func (m *memGraph) ListObjects(_ context.Context, subject, relation, objectType string) ([]string, error) {
	var ids []string
	for t := range m.tuples {
		if t.User == subject && t.Relation == relation && t.ObjectType() == objectType {
			ids = append(ids, t.ObjectID())
		}
	}
	return ids, nil
}

func (m *memGraph) Read(_ context.Context, q Query) ([]Tuple, error) {
	if err := q.Validate(); err != nil {
		return nil, err
	}
	var out []Tuple
	for t := range m.tuples {
		if q.Matches(t) {
			out = append(out, t)
		}
	}
	return out, nil
}

const dupOrMissing = "tuple to be written already existed or the tuple to be deleted did not exist"

func (m *memGraph) Write(_ context.Context, writes, deletes []Tuple) error {
	m.writes++
	if m.fail != nil {
		return m.fail
	}
	for _, t := range writes {
		if m.tuples[t] {
			return &ResponseError{Op: "write", Status: 400, Body: `{"message":"cannot write a tuple which already exists: ` + dupOrMissing + `"}`}
		}
	}
	for _, t := range deletes {
		if !m.tuples[t] {
			return &ResponseError{Op: "write", Status: 400, Body: `{"message":"cannot delete a tuple which does not exist: ` + dupOrMissing + `"}`}
		}
	}
	for _, t := range writes {
		m.tuples[t] = true
	}
	for _, t := range deletes {
		delete(m.tuples, t)
	}
	return nil
}

func (m *memGraph) has(user, relation, object string) bool {
	return m.tuples[Tuple{User: user, Relation: relation, Object: object}]
}

func TestGrantResourceOwnerIsIdempotent(t *testing.T) {
	ctx := context.Background()
	g := newMem()
	for range 2 {
		if err := GrantResourceOwner(ctx, g, "r1", "w1", "User:u1", AgentOwnerRelations()); err != nil {
			t.Fatal(err)
		}
	}
	for _, rel := range []string{RelReader, RelWriter, RelManager, RelInvoker} {
		if !g.has("User:u1", rel, "resource:r1") {
			t.Errorf("missing %s", rel)
		}
	}
	if !g.has("project:w1-root", RelProject, "resource:r1") {
		t.Error("resource not attached to the root project")
	}
	if len(g.tuples) != 5 {
		t.Errorf("tuples = %v", g.tuples)
	}
}

func TestGrantFailureIsOwnershipError(t *testing.T) {
	g := newMem()
	g.fail = &UnavailableError{Op: "write", Err: errors.New("connection refused")}
	err := GrantResourceOwner(context.Background(), g, "r1", "w1", "User:u1", OwnerRelations())
	var oe *OwnershipError
	if !errors.As(err, &oe) || oe.Error() != "OpenFGA grant write failed" {
		t.Fatalf("err = %v", err)
	}
	var ue *UnavailableError
	if !errors.As(err, &ue) {
		t.Error("cause not kept")
	}
	if g.writes != 1 {
		t.Errorf("kept writing after a failure: %d", g.writes)
	}
}

func TestIdempotencyNeedsA400(t *testing.T) {
	g := newMem()
	g.fail = &ResponseError{Op: "write", Status: 500, Body: "tuple to be written already existed"}
	if _, err := WriteIdempotent(context.Background(), g, Tuple{User: "User:u1", Relation: RelReader, Object: "resource:r1"}); err == nil {
		t.Fatal("a 500 read as an existing tuple")
	}
}

func TestDeleteIdempotentReportsChange(t *testing.T) {
	ctx := context.Background()
	g := newMem()
	tu := Tuple{User: "Agent:a1", Relation: RelConnectionUser, Object: "resource:c1"}
	if changed, err := WriteIdempotent(ctx, g, tu); err != nil || !changed {
		t.Fatalf("first write: %v %v", changed, err)
	}
	if changed, err := WriteIdempotent(ctx, g, tu); err != nil || changed {
		t.Fatalf("second write: %v %v", changed, err)
	}
	if changed, err := DeleteIdempotent(ctx, g, tu); err != nil || !changed {
		t.Fatalf("first delete: %v %v", changed, err)
	}
	if changed, err := DeleteIdempotent(ctx, g, tu); err != nil || changed {
		t.Fatalf("second delete: %v %v", changed, err)
	}
}

func TestWorkspaceMembership(t *testing.T) {
	ctx := context.Background()
	g := newMem()
	if err := SeedWorkspace(ctx, g, "w1", "u1"); err != nil {
		t.Fatal(err)
	}
	for range 2 {
		if err := GrantWorkspaceMembership(ctx, g, "w1", "User:u2"); err != nil {
			t.Fatal(err)
		}
	}
	if !g.has("User:u2", RelReader, "project:w1-root") {
		t.Error("baseline role missing")
	}
	g.tuples[Tuple{User: "Agent:a1", Relation: RelMembers, Object: "Workspace:w1"}] = true
	ids, err := WorkspaceMemberIDs(ctx, g, "w1")
	if err != nil || !slices.Equal(ids, []string{"u1", "u2"}) {
		t.Fatalf("members = %v %v", ids, err)
	}
	ws, err := MemberWorkspaceIDs(ctx, g, "u2")
	if err != nil || !slices.Equal(ws, []string{"w1"}) {
		t.Fatalf("workspaces = %v %v", ws, err)
	}
	for range 2 {
		if err := RevokeWorkspaceMembership(ctx, g, "w1", "u2"); err != nil {
			t.Fatal(err)
		}
	}
	if ok, _ := IsWorkspaceMember(ctx, g, "w1", "u2"); ok {
		t.Error("still a member")
	}
	if ok, _ := IsWorkspaceMember(ctx, g, "w1", "u1"); !ok {
		t.Error("owner lost membership")
	}
}

func TestAgentEnrollment(t *testing.T) {
	ctx := context.Background()
	g := newMem()
	if err := EnrollAgent(ctx, g, "a1", "w1"); err != nil {
		t.Fatal(err)
	}
	if !g.has("Agent:a1", RelMembers, "Workspace:w1") || !g.has("Agent:a1", RelReader, "project:w1-root") || !g.has("Agent:a1", RelInvoker, "resource:a1") {
		t.Fatalf("enrollment = %v", g.tuples)
	}
	if err := WithdrawAgent(ctx, g, "a1", "w1"); err != nil {
		t.Fatal(err)
	}
	if err := WithdrawAgent(ctx, g, "a1", "w1"); err != nil {
		t.Fatal(err)
	}
	if len(g.tuples) != 0 {
		t.Fatalf("left %v", g.tuples)
	}
}

func TestRevokeResourceDeletesOnlyItsTuples(t *testing.T) {
	ctx := context.Background()
	g := newMem()
	_ = GrantResourceOwner(ctx, g, "r1", "w1", "User:u1", OwnerRelations())
	_ = GrantResourceOwner(ctx, g, "r2", "w1", "User:u1", OwnerRelations())
	if err := RevokeResource(ctx, g, "r1"); err != nil {
		t.Fatal(err)
	}
	for tu := range g.tuples {
		if tu.Object == "resource:r1" {
			t.Errorf("left %v", tu)
		}
	}
	if len(g.tuples) != 4 {
		t.Errorf("r2 touched: %v", g.tuples)
	}
}

func TestConnections(t *testing.T) {
	ctx := context.Background()
	g := newMem()
	if err := MakePersonal(ctx, g, "c1"); err != nil {
		t.Fatal(err)
	}
	personal, err := PersonalConnectionIDs(ctx, g, []string{"c1", "c2"})
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := personal["c1"]; !ok || len(personal) != 1 {
		t.Fatalf("personal = %v", personal)
	}
	if err := ShareWithWorkspace(ctx, g, "c1"); err != nil {
		t.Fatal(err)
	}
	if err := ShareWithWorkspace(ctx, g, "c1"); err != nil {
		t.Fatal(err)
	}
	if err := LendConnection(ctx, g, "c1", "a1"); err != nil || !g.has("Agent:a1", RelConnectionUser, "resource:c1") {
		t.Fatalf("lend: %v", err)
	}
	if err := WithdrawConnection(ctx, g, "c1", "a1"); err != nil || len(g.tuples) != 0 {
		t.Fatalf("withdraw: %v %v", err, g.tuples)
	}
}

func TestQueryRefusesStoreScan(t *testing.T) {
	for _, q := range []Query{{}, {Type: TypeResource}, {Relation: RelMembers, User: "User:u1"}, {Type: "resource:r1", ID: "x"}} {
		if q.Validate() == nil {
			t.Errorf("%+v accepted", q)
		}
	}
	if (Query{Type: TypeWorkspace, User: "User:u1"}).Validate() != nil {
		t.Error("type plus user refused")
	}
}

func TestNames(t *testing.T) {
	if UserSubject("u1") != "User:u1" || UserSubject("User:u1") != "User:u1" {
		t.Error("UserSubject")
	}
	if RootProject("w1") != "project:w1-root" {
		t.Error("RootProject")
	}
	if typ, id := SplitObject("resource:a:b"); typ != "resource" || id != "a:b" {
		t.Error("SplitObject")
	}
}

func TestPermissions(t *testing.T) {
	ctx := context.Background()
	g := newMem()
	g.tuples[Tuple{User: "User:u1", Relation: CanInvoke, Object: "resource:a1"}] = true
	p := NewPermissions(g, nil)
	cases := map[string]string{
		"view": CanRead, "use": CanRead, "read": CanRead, "operate": CanRead, "connect": CanRead,
		"execute": CanInvoke, "use_secret": CanUseSecret, "use_connection": CanUseConnection,
		"edit": CanWrite, "write": CanWrite, "update": CanWrite, "configure": CanWrite,
		"manage": CanManage, "own": CanManage, "delete": CanManage,
	}
	for verb, want := range cases {
		if got, ok := RelationForPermission(verb); !ok || got != want {
			t.Errorf("%s -> %s", verb, got)
		}
	}
	if _, ok := RelationForPermission("admin"); ok {
		t.Error("unmapped verb mapped")
	}
	if ok, err := p.Check(ctx, "User:u1", "execute", "agent", "a1"); !ok || err != nil {
		t.Error("execute refused")
	}
	if ok, _ := p.Check(ctx, "User:u1", "view", "agent", "a1"); ok {
		t.Error("invoke implied read")
	}
	if ok, _ := p.Check(ctx, "User:u9", "delete", "model_instance", "m1"); !ok {
		t.Error("ungoverned type checked")
	}
	if err := p.Require(ctx, authn.Subject{Kind: authn.SubjectUser, ID: "u1"}, "bogus", "agent", "a1"); !errors.Is(err, ErrDenied) {
		t.Errorf("unmapped verb: %v", err)
	}
}

type ownedFunc func(ctx context.Context, userID string) ([]string, error)

func (f ownedFunc) OwnedWorkspaceIDs(ctx context.Context, userID string) ([]string, error) {
	return f(ctx, userID)
}

func caller(t *testing.T, userID, wsID string) *authn.Caller {
	t.Helper()
	ws, err := scope.NewWorkspace(wsID, "slug-"+wsID)
	if err != nil {
		t.Fatal(err)
	}
	return &authn.Caller{Principal: authn.Principal{UserID: userID}, Workspace: ws}
}

func TestAdmins(t *testing.T) {
	ctx := context.Background()
	lookups := 0
	owned := ownedFunc(func(_ context.Context, userID string) ([]string, error) {
		lookups++
		if userID == "broken" {
			return nil, errors.New("db down")
		}
		return []string{"team"}, nil
	})
	a := NewAdmins(WorkspaceScoped{}, owned, nil)

	c := caller(t, "u1", "team")
	if err := a.Require(ctx, c); err != nil {
		t.Fatalf("owner refused: %v", err)
	}
	if lookups != 1 || !slices.Equal(c.AdminWorkspaces, []string{"team"}) {
		t.Fatalf("resolution: %d %v", lookups, c.AdminWorkspaces)
	}
	_ = a.Require(ctx, c)
	if lookups != 1 {
		t.Error("resolved twice")
	}

	if err := a.Require(ctx, caller(t, "u1", "other")); !errors.Is(err, ErrNotWorkspaceAdmin) {
		t.Errorf("non-owner: %v", err)
	}
	if err := a.Require(ctx, caller(t, "u1", "u1")); err != nil {
		t.Errorf("personal workspace: %v", err)
	}

	broken := caller(t, "broken", "team")
	if err := a.Require(ctx, broken); !errors.Is(err, ErrNotWorkspaceAdmin) {
		t.Errorf("failed lookup granted: %v", err)
	}
	if broken.AdminWorkspaces == nil {
		t.Error("failed lookup left unresolved")
	}

	run := caller(t, "u1", "team")
	run.Subject = &authn.Subject{Kind: authn.SubjectAgent, ID: "a1"}
	if ok, _ := a.IsAdmin(ctx, run); ok {
		t.Error("an agent administers")
	}
	if err := a.RequireOf(ctx, run, "team"); !errors.Is(err, ErrNotWorkspaceAdmin) {
		t.Error("an agent administers by path")
	}
	if err := a.RequireOf(ctx, caller(t, "u1", "x"), ""); !errors.Is(err, ErrWorkspaceRequired) {
		t.Error("empty target accepted")
	}
	if err := a.RequireOf(ctx, caller(t, "u1", "x"), "team"); err != nil {
		t.Errorf("path workspace: %v", err)
	}
}

func TestWorkspaceScoped(t *testing.T) {
	ctx := context.Background()
	c := *caller(t, "u1", "w1")
	if ok, _ := (WorkspaceScoped{}).CanWrite(ctx, c, "w1"); !ok {
		t.Error("own workspace not writable")
	}
	if ok, _ := (WorkspaceScoped{}).CanWrite(ctx, c, "w2"); ok {
		t.Error("other workspace writable")
	}
	if ws, _ := (WorkspaceScoped{}).AccessibleWorkspaces(ctx, c.Principal); ws == nil || len(ws) != 0 {
		t.Error("accessible not empty")
	}
}

func TestAuthorizeAgentAction(t *testing.T) {
	if AuthorizeAgentAction(nil, AgentExecute, "w1", "a1").Allowed {
		t.Error("anonymous allowed")
	}
	key := &authn.Principal{UserID: "u1", BoundAgentID: "a1", BoundWorkspaceID: "w1", AccessibleWorkspaces: []string{"w1"}}
	if !AuthorizeAgentAction(key, AgentExecute, "w1", "a1").Allowed {
		t.Error("agent key refused its agent")
	}
	if d := AuthorizeAgentAction(key, AgentExecute, "w1", "a2"); d.Allowed || d.Reason != "key bound to agent a1" {
		t.Errorf("agent key reached another agent: %+v", d)
	}
	member := &authn.Principal{UserID: "u1", AccessibleWorkspaces: []string{"w1"}}
	if !AuthorizeAgentAction(member, AgentRead, "w1", "a1").Allowed || AuthorizeAgentAction(member, AgentRead, "w2", "a1").Allowed {
		t.Error("workspace scope")
	}
}

type memLedger struct {
	applied  map[string]struct{}
	recorded []string
}

func (l *memLedger) Applied(context.Context) (map[string]struct{}, error) { return l.applied, nil }

func (l *memLedger) Record(ctx context.Context, id string, fn func(context.Context, db.Querier) error) error {
	if err := fn(ctx, nil); err != nil {
		return err
	}
	l.applied[id] = struct{}{}
	l.recorded = append(l.recorded, id)
	return nil
}

func TestApplyPendingGraphMigrations(t *testing.T) {
	ctx := context.Background()
	g := newMem()
	builds := 0
	provider := OnceGraph(func(context.Context) (Graph, error) { builds++; return g, nil })
	var ran []string
	step := func(id string, fail bool, write bool) GraphMigration {
		return GraphMigration{ID: id, Apply: func(ctx context.Context, _ db.Querier, graph GraphProvider) error {
			ran = append(ran, id)
			if fail {
				return errors.New("boom")
			}
			if !write {
				return nil
			}
			gr, err := graph(ctx)
			if err != nil {
				return err
			}
			_, err = WriteIdempotent(ctx, gr, Tuple{User: "User:" + id, Relation: RelReader, Object: "resource:r"})
			return err
		}}
	}
	ledger := &memLedger{applied: map[string]struct{}{"20260101_0000_done": {}}}
	steps := []GraphMigration{
		step("20260101_0000_done", false, true),
		step("20260102_0000_empty", false, false),
		step("20260103_0000_write", false, true),
		step("20260104_0000_again", false, true),
	}
	got, err := ApplyPendingGraphMigrations(ctx, ledger, steps, provider, nil)
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(got, []string{"20260102_0000_empty", "20260103_0000_write", "20260104_0000_again"}) {
		t.Fatalf("applied %v", got)
	}
	if builds != 1 {
		t.Errorf("graph built %d times", builds)
	}

	ledger = &memLedger{applied: map[string]struct{}{}}
	ran = nil
	steps = []GraphMigration{step("20260101_0000_a", false, false), step("20260102_0000_b", true, false), step("20260103_0000_c", false, false)}
	got, err = ApplyPendingGraphMigrations(ctx, ledger, steps, provider, nil)
	if err == nil || !strings.Contains(err.Error(), "20260102_0000_b") {
		t.Fatalf("err = %v", err)
	}
	if !slices.Equal(got, []string{"20260101_0000_a"}) || !slices.Equal(ledger.recorded, []string{"20260101_0000_a"}) || len(ran) != 2 {
		t.Fatalf("got %v recorded %v ran %v", got, ledger.recorded, ran)
	}

	lazy := OnceGraph(func(context.Context) (Graph, error) {
		t.Fatal("graph built for a step with nothing to write")
		return nil, nil
	})
	if _, err := ApplyPendingGraphMigrations(ctx, &memLedger{applied: map[string]struct{}{}}, []GraphMigration{step("20260101_0000_x", false, false)}, lazy, nil); err != nil {
		t.Fatal(err)
	}
}

func TestCheckMigrations(t *testing.T) {
	bad := [][]GraphMigration{
		{{ID: "2026_secret"}},
		{{ID: "20260101_0000_a"}, {ID: "20260101_0000_a"}},
		{{ID: "20260102_0000_a"}, {ID: "20260101_0000_b"}},
		{{ID: "20260101_0000_A"}},
	}
	for _, steps := range bad {
		if CheckMigrations(steps) == nil {
			t.Errorf("%v accepted", steps)
		}
	}
	if err := CheckMigrations([]GraphMigration{{ID: "20261109_2300_secret_owners"}}); err != nil {
		t.Error(err)
	}
}

func TestLoadConfig(t *testing.T) {
	l := config.FromMap(map[string]string{"AGENTAREA_AUTHZ_FGA_BOOTSTRAP": "true", "AGENTAREA_AUTHZ_FGA_TIMEOUT": "2500ms"})
	c := LoadConfig(l)
	if err := l.Err(); err != nil {
		t.Fatal(err)
	}
	if c.Backend != "openfga" || c.URL != "http://openfga:8080" || c.StoreName != "agentarea" || c.Timeout != 2500*time.Millisecond || !c.Bootstrap || c.ApplyModel {
		t.Fatalf("%+v", c)
	}

	l = config.FromMap(map[string]string{"AGENTAREA_AUTHZ_FGA_TIMEOUT": "10", "AGENTAREA_AUTHZ_BACKEND": "keto"})
	LoadConfig(l)
	err := l.Err()
	for _, name := range []string{"AGENTAREA_AUTHZ_FGA_TIMEOUT", "AGENTAREA_AUTHZ_BACKEND", "AGENTAREA_AUTHZ_FGA_STORE_ID"} {
		if err == nil || !strings.Contains(err.Error(), name) {
			t.Errorf("%s not reported: %v", name, err)
		}
	}
}
