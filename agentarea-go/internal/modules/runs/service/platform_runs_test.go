package service

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

func callerIn(t *testing.T, workspaceID, userID string) authn.Caller {
	t.Helper()
	ws, err := scope.NewWorkspace(workspaceID, "ws")
	if err != nil {
		t.Fatal(err)
	}
	return authn.Caller{Principal: authn.Principal{UserID: userID}, Workspace: ws}
}

func TestPlatformStartRefusesWithoutExecuteOnTheAgent(t *testing.T) {
	var asked []string
	s := NewSurface(SurfaceDeps{
		Policies: &taskPolicies{}, Launcher: &fakeLauncher{}, Log: quiet(), Now: fixedNow,
		Permissions: func(_ context.Context, _ authn.Caller, perm, typ, id string) error {
			asked = append(asked, perm+" "+typ+" "+id)
			return authz.ErrDenied
		},
	})
	c := callerIn(t, uuid.NewString(), "u1")
	agent := uuid.NewString()
	_, err := s.PlatformRuns().Start(context.Background(), c, api.RunStart{AgentID: agent, Description: "go"})
	if err == nil || err.Error() != "Permission denied" {
		t.Fatalf("err = %v", err)
	}
	if len(asked) != 1 || asked[0] != "execute agent "+agent {
		t.Fatalf("asked %v", asked)
	}
	if _, err := s.PlatformRuns().Start(context.Background(), c, api.RunStart{AgentID: "bot", Description: "go"}); err == nil || err.Error() != "agent_id must be a UUID" {
		t.Fatalf("err = %v", err)
	}
}

func TestPlatformStartNeedsTheLauncher(t *testing.T) {
	s := NewSurface(SurfaceDeps{Log: quiet(), Now: fixedNow})
	_, err := s.PlatformRuns().Start(context.Background(), callerIn(t, uuid.NewString(), "u1"), api.RunStart{AgentID: uuid.NewString(), Description: "go"})
	if err == nil || !strings.Contains(err.Error(), "launcher") {
		t.Fatalf("err = %v", err)
	}
}

func TestRunCreateValidatesAsRunCreate(t *testing.T) {
	agent := uuid.NewString()
	past := fixedNow().Add(-time.Hour).Format(time.RFC3339)
	future := fixedNow().Add(time.Hour).Format(time.RFC3339)
	naive := "2026-11-12T11:00:00"
	for _, c := range []struct {
		in   api.RunStart
		want string
	}{
		{api.RunStart{AgentID: "x", Description: "d"}, "agent_id: Input should be a valid UUID"},
		{api.RunStart{AgentID: agent}, "description: String should have at least 1 character"},
		{api.RunStart{AgentID: agent, Description: strings.Repeat("é", runDescriptionMax+1)}, "description: String should have at most"},
		{api.RunStart{AgentID: agent, Description: "d", Parameters: map[string]any{"session": 1}}, "parameters: session is set by the trigger"},
		{api.RunStart{AgentID: agent, Description: "d", Parameters: map[string]any{"model_override": "gpt"}}, "parameters: model_override must be a model instance id"},
		{api.RunStart{AgentID: agent, Description: "d", ScheduledAt: &past}, "scheduled_at must be in the future"},
		{api.RunStart{AgentID: agent, Description: "d", ScheduledAt: &naive}, "scheduled_at must include a UTC offset"},
	} {
		_, _, err := runCreate(c.in, fixedNow())
		if err == nil || !strings.Contains(err.Error(), c.want) {
			t.Fatalf("%+v: err = %v, want %q", c.in, err, c.want)
		}
	}
	params, at, err := runCreate(api.RunStart{AgentID: agent, Description: "d", Parameters: map[string]any{"k": "v"}, ScheduledAt: &future}, fixedNow())
	if err != nil || params["k"] != "v" || at == nil || !at.Equal(fixedNow().Add(time.Hour)) {
		t.Fatalf("params %v at %v err %v", params, at, err)
	}
}

func TestGrantValidatesAsContinueTaskPayload(t *testing.T) {
	bad, zero := "lots", "0"
	for _, c := range []struct {
		in   api.RunGrant
		want string
	}{
		{api.RunGrant{Iterations: -1}, "additional_iterations: Input should be greater than or equal to 0"},
		{api.RunGrant{Tokens: maxGrantTokens + 1}, "additional_tokens: Input should be less than or equal to"},
		{api.RunGrant{BudgetUSD: &bad}, "additional_budget_usd: Value error, 'lots' is not a money amount"},
		{api.RunGrant{BudgetUSD: &zero}, "additional_budget_usd: Input should be greater than 0"},
	} {
		if _, err := grant(c.in); err == nil || !strings.Contains(err.Error(), c.want) {
			t.Fatalf("%+v: err = %v", c.in, err)
		}
	}
	one := "1.50"
	got, err := grant(api.RunGrant{Iterations: 3, BudgetUSD: &one})
	if err != nil || got.Iterations != 3 || got.Budget == nil {
		t.Fatalf("%+v %v", got, err)
	}
}

func TestEventProjectionKeepsTheFactsWorthReading(t *testing.T) {
	call := wirejson.Object{}
	call.Set("tool_name", "shell")
	call.Set("tool_call_id", "t1")
	args := wirejson.Object{}
	args.Set("cmd", "ls")
	args.Set("cwd", "/")
	call.Set("arguments", args)
	call.Set("noise", 1)

	hidden := eventProjection("tool.call", call, false)
	if _, ok := hidden.Get("arguments"); ok {
		t.Fatalf("arguments shown unrevealed: %v", hidden)
	}
	names, _ := hidden.Get("argument_names")
	if n, ok := names.([]any); !ok || len(n) != 2 || n[0] != "cmd" || n[1] != "cwd" {
		t.Fatalf("argument_names %v", names)
	}
	if _, ok := hidden.Get("noise"); ok {
		t.Fatal("noise kept")
	}
	if _, ok := eventProjection("tool.call", call, true).Get("arguments"); !ok {
		t.Fatal("revealed lost arguments")
	}

	done := wirejson.Object{}
	done.Set("message", "ok")
	done.Set("status", "completed")
	done.Set("error", nil)
	got := eventProjection("task.completed", done, false)
	if len(got) != 2 || got[0].Key != "message" || got[1].Key != "status" {
		t.Fatalf("terminal %v", got)
	}

	usage := wirejson.Object{}
	inner := wirejson.Object{}
	inner.Set("total_tokens", 9)
	usage.Set("usage", inner)
	llm := wirejson.Object{}
	llm.Set("model_id", "m1")
	llm.Set("usage", usage)
	got = eventProjection("llm.call.completed", llm, false)
	if u, ok := got.Get("usage"); !ok || u.(wirejson.Object)[0].Key != "total_tokens" {
		t.Fatalf("usage %v", got)
	}
}

func TestPlatformRunsActOnlyForTheStarterOrAnAdmin(t *testing.T) {
	d := openDB(t)
	p, taskID := seed(t, d)
	admin := false
	s := NewSurface(SurfaceDeps{
		DB: d, Executor: &fakeExecutor{}, Log: quiet(), Now: fixedNow,
		Admin: func(context.Context) error {
			if admin {
				return nil
			}
			return authz.ErrNotWorkspaceAdmin
		},
	})
	runs := s.PlatformRuns()
	ctx := context.Background()
	other := callerIn(t, p.WorkspaceID, "user-2")
	for name, call := range map[string]func() error{
		"cancel": func() error { _, err := runs.Cancel(ctx, other, taskID); return err },
		"pause":  func() error { _, err := runs.Pause(ctx, other, taskID); return err },
		"resume": func() error { _, err := runs.Resume(ctx, other, taskID); return err },
		"input": func() error {
			_, err := runs.SendInput(ctx, other, taskID, "q1", map[string]any{"a": "b"})
			return err
		},
		"command": func() error {
			msg := "hi"
			_, err := runs.SendCommand(ctx, other, taskID, api.RunCommand{Command: "queue_message", Message: &msg})
			return err
		},
		"continue": func() error { _, err := runs.ContinueRun(ctx, other, taskID, api.RunGrant{Iterations: 1}); return err },
		"retry":    func() error { return runs.Retry(ctx, other, taskID) },
	} {
		if err := call(); err == nil || err.Error() != "Only a workspace admin may perform this action" {
			t.Fatalf("%s: err = %v", name, err)
		}
	}
	if _, err := runs.Cancel(ctx, other, uuid.NewString()); err == nil || err.Error() != "Run not found" {
		t.Fatalf("missing run: %v", err)
	}
	got, err := runs.Get(ctx, other, taskID)
	if err != nil || got.Query != "d" || got.RunID != taskID {
		t.Fatalf("get %+v %v", got, err)
	}
	admin = true
	if _, err := runs.Events(ctx, other, taskID, 10, 0, nil); err != nil {
		t.Fatalf("admin events: %v", err)
	}
}
