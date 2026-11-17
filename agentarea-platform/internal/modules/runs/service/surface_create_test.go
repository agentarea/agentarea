package service

import (
	"context"
	"errors"
	"net/http"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
)

func TestSelectionKeyComparesCapabilityIdentities(t *testing.T) {
	id := uuid.NewString()
	a, ok := selectionKey(map[string]any{"mcps": []any{map[string]any{"instance_id": id}}, "files": []any{"/a/./b"}})
	if !ok {
		t.Fatal("refused")
	}
	b, _ := selectionKey(map[string]any{"mcp": []any{id}, "files": []any{"a/b"}})
	if a != b {
		t.Fatalf("%q != %q", a, b)
	}
	if _, ok := selectionKey(map[string]any{"skills": []any{"not-a-uuid"}}); ok {
		t.Fatal("a malformed skill id must refuse routing")
	}
	if _, ok := selectionKey(map[string]any{"files": []any{"../x"}}); ok {
		t.Fatal("an escaping path must refuse routing")
	}
}

func TestReconstructAppendsTheMissingTurns(t *testing.T) {
	empty := reconstruct(nil, "do it", "done")
	if len(empty.appended) != 2 || empty.appended[0].Role != "user" || empty.appended[1].Role != "assistant" {
		t.Fatalf("appended %+v", empty.appended)
	}
	if empty.nextSeq != 2 || empty.iteration != 1 || !empty.systemMissing {
		t.Fatalf("%+v", empty)
	}
	log := []store.OutlineEntry{
		{Seq: 0, Kind: "message", Role: "system"}, {Seq: 1, Kind: "message", Role: "user"},
		{Seq: 2, Kind: "message", Role: "assistant", ToolCalls: 2}, {Seq: 3, Kind: "message", Role: "tool"},
		{Seq: 4, Kind: "message", Role: "assistant"}, {Seq: 5, Kind: "event"},
	}
	got := reconstruct(log, "q", "final")
	if len(got.appended) != 0 || got.nextSeq != 6 || got.iteration != 2 || got.toolCalls != 2 || got.systemMissing {
		t.Fatalf("%+v", got)
	}
}

func TestDedupeNameNumbersRepeats(t *testing.T) {
	used := map[string]bool{"a.txt": true, "a-1.txt": true}
	if got := dedupeName("a.txt", used); got != "a-2.txt" {
		t.Fatal(got)
	}
}

func TestLiveSandboxPathRefusesEscapes(t *testing.T) {
	for _, bad := range []string{"/etc", "a/../b", "./a", "a\\b", ""} {
		if _, err := liveSandboxPath(bad, false); err == nil {
			t.Fatalf("%q admitted", bad)
		}
	}
	if p, err := liveSandboxPath("a//b/", false); err != nil || p != "a/b" {
		t.Fatalf("%q %v", p, err)
	}
	if p, err := liveSandboxPath("", true); err != nil || p != "" {
		t.Fatalf("%q %v", p, err)
	}
}

func TestCapRefusalNamesTheCap(t *testing.T) {
	ws, _ := scope.NewWorkspace(uuid.NewString(), "")
	r := capRefusal(ws, money.MustParse("12.5"), money.MustParse("10"), "EUR", "agent-1", true)
	if r.Detail != "Agent monthly LLM spend cap reached (12.5 EUR/10 EUR)" || r.Status != http.StatusPaymentRequired {
		t.Fatalf("%+v", r)
	}
	if v, _ := r.Extra.Get("cap_usd"); v != 10.0 {
		t.Fatalf("cap_usd %v", v)
	}
}

type taskPolicies struct {
	refuse bool
	got    []governanceapi.TaskRequest
}

func (f *taskPolicies) Resolve(context.Context, governanceapi.RunPrincipal, *governanceapi.Policy) (governanceapi.Policy, error) {
	return governanceapi.Policy{}, nil
}

func (f *taskPolicies) Delegation(context.Context, governanceapi.RunPrincipal, governanceapi.DelegationRequest) (governanceapi.Policy, governanceapi.Snapshot, error) {
	return governanceapi.Policy{}, governanceapi.Snapshot{}, nil
}

func (f *taskPolicies) Task(_ context.Context, _ governanceapi.RunPrincipal, req governanceapi.TaskRequest) (governanceapi.Policy, governanceapi.Snapshot, error) {
	f.got = append(f.got, req)
	if f.refuse {
		return governanceapi.Policy{}, governanceapi.Snapshot{}, governanceapi.ErrPolicyRefused
	}
	return governanceapi.Policy{}, governanceapi.Snapshot{Revision: 1, ResolvedAt: fixedNow()}, nil
}

type fakeLauncher struct {
	fail     error
	launched []store.StoredTask
	resumed  []ResumeSpec
}

func (f *fakeLauncher) Launch(_ context.Context, _ string, t store.StoredTask) (Launched, error) {
	if f.fail != nil {
		return Launched{}, f.fail
	}
	f.launched = append(f.launched, t)
	return Launched{ExecutionID: "task-" + t.ID}, nil
}

func (f *fakeLauncher) Resume(_ context.Context, _ string, _ store.StoredTask, r ResumeSpec) error {
	f.resumed = append(f.resumed, r)
	return nil
}

type fakeDefinitions map[string]agentsapi.Definition

func (f fakeDefinitions) Definition(_ context.Context, _ scope.Workspace, id string) (agentsapi.Definition, error) {
	d, ok := f[id]
	if !ok {
		return d, agentsapi.ErrNotFound
	}
	return d, nil
}

type definedAgents struct {
	agentsapi.Lookup
	defs fakeDefinitions
}

func (d definedAgents) AgentExists(_ context.Context, _ scope.Workspace, id string) (bool, error) {
	_, ok := d.defs[id]
	return ok, nil
}

type closedExecutor struct {
	fakeExecutor
	signals int
}

func (c *closedExecutor) Status(context.Context, string) (durable.Result, error) {
	return durable.Result{Status: durable.StatusFailed}, nil
}

func (c *closedExecutor) Signal(context.Context, string, string, ...any) error {
	c.signals++
	return nil
}

func createSurface(t *testing.T) (*Surface, Principal, *taskPolicies, *fakeLauncher, *closedExecutor, context.Context) {
	t.Helper()
	d := openDB(t)
	p, _ := seed(t, d)
	pol, l, x := &taskPolicies{}, &fakeLauncher{}, &closedExecutor{}
	defs := fakeDefinitions{p.AgentID: {ID: p.AgentID, Name: "Bot", ModelID: uuid.NewString()}}
	s := NewSurface(SurfaceDeps{
		DB: d, Executor: x, Log: quiet(), Now: fixedNow, Currency: func() string { return "EUR" },
		Policies: pol, Launcher: l, Resumer: l, Audit: &fakeAudit{},
		Definitions: defs, Agents: definedAgents{defs: defs},
		Permissions: func(context.Context, authn.Caller, string, string, string) error { return nil },
	})
	ws, _ := scope.NewWorkspace(p.WorkspaceID, "ws")
	ctx := authn.WithCaller(context.Background(), authn.Caller{Principal: authn.Principal{UserID: p.UserID}, Workspace: ws})
	return s, p, pol, l, x, ctx
}

func TestCreateStoresTheSnapshotAndLaunches(t *testing.T) {
	s, p, pol, l, _, ctx := createSurface(t)
	turns := int64(3)
	got, err := s.Create(ctx, CreateRequest{
		AgentID: p.AgentID, Description: "go", ExecutionTurns: &turns,
		Parameters: map[string]any{"max_iterations": 5, "k": "v"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if got.Task.Status != "running" || got.AgentName != "Bot" || len(l.launched) != 1 {
		t.Fatalf("%+v launched %d", got.Task, len(l.launched))
	}
	if pol.got[0].MaxIterations != 5 || *pol.got[0].ExecutionTurns != 3 {
		t.Fatalf("policy request %+v", pol.got[0])
	}
	if _, kept := got.Task.Parameters.Get("max_iterations"); kept {
		t.Fatal("max_iterations must leave the parameters")
	}
	snap, _ := got.Task.Metadata.Get("governance_snapshot")
	if snap == nil {
		t.Fatal("no governance snapshot")
	}
	if v, _ := got.Task.Metadata.Get("created_via"); v != "api" {
		t.Fatalf("created_via %v", v)
	}
	if got.Task.Provenance.OriginType == nil || *got.Task.Provenance.OriginType != "user" {
		t.Fatalf("provenance %+v", got.Task.Provenance)
	}
}

func TestCreateAuditsTheTask(t *testing.T) {
	s, p, _, _, _, ctx := createSurface(t)
	c, _ := authn.CallerFrom(ctx)
	c.Credential = &authn.Credential{Kind: authn.KindAPIKey, KeyID: "k1", Surface: authn.SurfaceAPI}
	got, err := s.Create(authn.WithCaller(context.Background(), c), CreateRequest{AgentID: p.AgentID, Description: "go"})
	if err != nil {
		t.Fatal(err)
	}
	lines := s.d.Audit.(*fakeAudit).lines
	if len(lines) != 1 {
		t.Fatalf("audit %+v", lines)
	}
	for _, l := range lines {
		if l.Action != "task.create" || l.ResourceType != "task" || l.ResourceID != got.Task.ID ||
			l.ActorType != "user" || l.ActorID != p.UserID {
			t.Fatalf("audit %+v", l)
		}
		if l.Metadata["credential"] != "api_key" || l.Metadata["surface"] != "api" || l.Metadata["api_key_id"] != "k1" {
			t.Fatalf("metadata %v", l.Metadata)
		}
	}
}

func TestSubmitAuditsTheTaskForItsOwner(t *testing.T) {
	s, p, _, _, _, ctx := createSurface(t)
	ws, _ := scope.NewWorkspace(p.WorkspaceID, "")
	out, err := s.Submit(ctx, ws, api.TaskRequest{AgentID: p.AgentID, Description: "hi", UserID: p.UserID})
	if err != nil {
		t.Fatal(err)
	}
	lines := s.d.Audit.(*fakeAudit).lines
	if len(lines) != 1 {
		t.Fatalf("audit %+v", lines)
	}
	for _, l := range lines {
		if l.Action != "task.create" || l.ResourceID != out.TaskID || l.ActorID != p.UserID || len(l.Metadata) != 0 {
			t.Fatalf("audit %+v", l)
		}
	}
}

func TestRefusedCreateIsNotAudited(t *testing.T) {
	s, p, pol, _, _, ctx := createSurface(t)
	pol.refuse = true
	if _, err := s.Create(ctx, CreateRequest{AgentID: p.AgentID, Description: "go"}); err == nil {
		t.Fatal("policy refusal accepted")
	}
	if n := len(s.d.Audit.(*fakeAudit).lines); n != 0 {
		t.Fatalf("audit lines %d", n)
	}
}

func TestCreateRefusals(t *testing.T) {
	s, p, pol, l, _, ctx := createSurface(t)
	var r *Refusal

	pol.refuse = true
	_, err := s.Create(ctx, CreateRequest{AgentID: p.AgentID, Description: "go"})
	if !errors.As(err, &r) || r.Status != http.StatusUnprocessableEntity || !errors.Is(err, api.ErrTaskPolicyRejected) {
		t.Fatalf("policy: %v", err)
	}
	pol.refuse = false

	_, err = s.Create(ctx, CreateRequest{AgentID: uuid.NewString(), Description: "go"})
	var he *httpx.Error
	if !errors.As(err, &he) || he.Status != http.StatusNotFound {
		t.Fatalf("unknown agent: %v", err)
	}

	_, err = s.Create(ctx, CreateRequest{AgentID: p.AgentID, Description: "go", EndUserID: ptr("eu")})
	if !errors.As(err, &he) || he.Status != http.StatusForbidden {
		t.Fatalf("session caller with end_user_id: %v", err)
	}

	l.fail = errors.New("temporal down")
	_, err = s.Create(ctx, CreateRequest{AgentID: p.AgentID, Description: "go"})
	if !errors.As(err, &r) || r.Status != http.StatusServiceUnavailable || r.Detail != "Task dispatch failed" {
		t.Fatalf("dispatch: %v", err)
	}
	failed := count(t, s.d.DB, p, `SELECT count(*) FROM tasks WHERE status = 'failed' AND error = 'Task dispatch failed' AND workspace_id = $1`, p.WorkspaceID)
	if failed != 1 {
		t.Fatalf("failed tasks %d", failed)
	}
}

func ptr(s string) *string { return &s }

func TestSubmitRoutesASessionFollowUpIntoItsLiveTask(t *testing.T) {
	s, p, _, l, x, ctx := createSurface(t)
	ws, _ := scope.NewWorkspace(p.WorkspaceID, "")
	params := map[string]any{"trigger_id": "trg", "session": map[string]any{"continue": true, "key": "chat-1"}}
	first, err := s.Submit(ctx, ws, api.TaskRequest{AgentID: p.AgentID, Description: "hi", Parameters: params, UserID: p.UserID})
	if err != nil || first.Routed {
		t.Fatalf("%+v %v", first, err)
	}
	next, err := s.Submit(ctx, ws, api.TaskRequest{AgentID: p.AgentID, Description: "again", Parameters: params, UserID: p.UserID})
	if err != nil || !next.Routed || next.TaskID != first.TaskID || x.signals != 1 || len(l.launched) != 1 {
		t.Fatalf("%+v %v signals %d", next, err, x.signals)
	}
	other, err := s.Submit(ctx, ws, api.TaskRequest{AgentID: p.AgentID, Description: "x", Parameters: params, UserID: "someone-else"})
	if err != nil || other.Routed {
		t.Fatalf("another user's follow-up joined the task: %+v %v", other, err)
	}
}

func TestRetryContinuesAFailedRunFromItsLog(t *testing.T) {
	s, p, _, l, _, ctx := createSurface(t)
	got, err := s.Create(ctx, CreateRequest{AgentID: p.AgentID, Description: "go"})
	if err != nil {
		t.Fatal(err)
	}
	ws, _ := scope.NewWorkspace(p.WorkspaceID, "")
	if err := s.d.DB.Write(ctx, ws, func(ctx context.Context, tx db.Session) error {
		_, err := store.SetSurfaceTaskStatus(ctx, tx, got.Task.ID, "failed", "boom", time.Now())
		return err
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Retry(ctx, p.AgentID, got.Task.ID); err != nil {
		t.Fatal(err)
	}
	if len(l.resumed) != 1 || !l.resumed[0].Retry || l.resumed[0].NextSeq != 1 || l.resumed[0].Message != nil {
		t.Fatalf("resume %+v", l.resumed)
	}
	if n := count(t, s.d.DB, p, `SELECT count(*) FROM task_conversation_entries WHERE role = 'user' AND workspace_id = $1`, p.WorkspaceID); n != 1 {
		t.Fatalf("rebuilt user turns %d", n)
	}
	if n := count(t, s.d.DB, p, `SELECT count(*) FROM tasks WHERE status = 'running' AND id = '`+got.Task.ID+`'`); n != 1 {
		t.Fatal("retried task is not running")
	}
	if _, err := s.Retry(ctx, p.AgentID, got.Task.ID); err == nil {
		t.Fatal("a running task was retried")
	}
}

func TestStartDefinitionStoresProvenanceAndMergedParameters(t *testing.T) {
	s, p, _, l, _, ctx := createSurface(t)
	c, _ := authn.CallerFrom(ctx)
	defID := uuid.NewString()
	body, err := s.StartDefinition(ctx, c, api.DefinitionRun{
		DefinitionID: defID, AgentID: p.AgentID, Description: "from def",
		Parameters: map[string]any{"a": 1, "b": "x"}, CreatedVia: "mcp",
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(l.launched) != 1 {
		t.Fatalf("launched %d", len(l.launched))
	}
	id, _ := body.Get("id")
	tk, ok, err := s.loadTask(ctx, c.Workspace, id.(string))
	if err != nil || !ok {
		t.Fatalf("load %v %v", ok, err)
	}
	if v, _ := tk.Metadata.Get("created_via"); v != "mcp" {
		t.Fatalf("created_via %v", v)
	}
	if tk.Provenance.TaskDefinitionID == nil || *tk.Provenance.TaskDefinitionID != defID {
		t.Fatalf("provenance %+v", tk.Provenance)
	}
	if v, _ := tk.Parameters.Get("b"); v != "x" {
		t.Fatalf("parameters %+v", tk.Parameters)
	}
	if _, err := s.StartDefinition(ctx, c, api.DefinitionRun{DefinitionID: defID, AgentID: uuid.NewString()}); err == nil {
		t.Fatal("an unknown agent must refuse")
	}
}
