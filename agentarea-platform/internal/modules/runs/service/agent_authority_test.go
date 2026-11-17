package service

import (
	"context"
	"errors"
	"net/http"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

var errLookedUp = errors.New("the run was looked up")

// lookupFails is every read the surface makes: reaching one means the caller
// got past the authority checks that come before it.
type lookupFails struct{ db.Database }

func (lookupFails) Read(context.Context, scope.Workspace) (db.Session, func(), error) {
	return db.Session{}, nil, errLookedUp
}

type agentLookupFails struct{ agentsapi.Lookup }

func (agentLookupFails) AgentExists(context.Context, scope.Workspace, string) (bool, error) {
	return false, errLookedUp
}

type definitionFails struct{}

func (definitionFails) Definition(context.Context, scope.Workspace, string) (agentsapi.Definition, error) {
	return agentsapi.Definition{}, errLookedUp
}

func actingAs(c authn.Caller, agentID string) authn.Caller {
	c.Subject = &authn.Subject{Kind: authn.SubjectAgent, ID: agentID}
	return c
}

func refusedAsAgent(err error) bool {
	var he *httpx.Error
	if errors.As(err, &he) {
		return he.Status == http.StatusForbidden && he.Detail == humanOnly
	}
	return err != nil && err.Error() == humanOnly
}

// A run calls with its starter's user id, so every check that compared only
// the user id let the agent answer for the person who started it: decide its
// own held call, answer a question meant for a person, grant itself budget.
func TestAnAgentNeverDoesWhatOnlyAPersonMay(t *testing.T) {
	s := NewSurface(SurfaceDeps{
		DB: lookupFails{}, Agents: agentLookupFails{}, Definitions: definitionFails{},
		Executor: &fakeExecutor{}, Log: quiet(), Now: fixedNow,
	})
	runs := s.PlatformRuns()
	starter := callerIn(t, uuid.NewString(), "user-1")
	agentID, run := uuid.NewString(), uuid.NewString()
	text, budget := "5", money.MustParse("5")
	calls := map[string]func(context.Context, authn.Caller) error{
		"runs_resolve_escalation": func(ctx context.Context, c authn.Caller) error {
			_, err := runs.ResolveEscalation(ctx, c, run, "e1", true, "")
			return err
		},
		"runs_send_input": func(ctx context.Context, c authn.Caller) error {
			_, err := runs.SendInput(ctx, c, run, "q1", map[string]any{"a": "b"})
			return err
		},
		"runs_continue_run": func(ctx context.Context, c authn.Caller) error {
			_, err := runs.ContinueRun(ctx, c, run, api.RunGrant{Iterations: 1})
			return err
		},
		"runs_send_command update_budget": func(ctx context.Context, c authn.Caller) error {
			_, err := runs.SendCommand(ctx, c, run, api.RunCommand{Command: api.CommandUpdateBudget, BudgetUSD: &text})
			return err
		},
		"POST resolve-escalation": func(ctx context.Context, _ authn.Caller) error {
			_, err := s.ResolveEscalation(ctx, agentID, run, Resolution{EscalationID: "e1", Approved: true})
			return err
		},
		"POST input": func(ctx context.Context, _ authn.Caller) error {
			_, err := s.SubmitInput(ctx, agentID, run, InputSubmission{InputRequestID: "q1"})
			return err
		},
		"POST a2ui/action": func(ctx context.Context, _ authn.Caller) error {
			_, err := s.SendA2UIAction(ctx, agentID, run, A2UIAction{Name: "submit"})
			return err
		},
		"POST continue": func(ctx context.Context, _ authn.Caller) error {
			_, err := s.ContinueExecution(ctx, run, Continuation{Iterations: 1})
			return err
		},
		"POST command update_budget": func(ctx context.Context, _ authn.Caller) error {
			_, err := s.SendCommand(ctx, agentID, run, Command{Command: api.CommandUpdateBudget, BudgetUSD: &budget})
			return err
		},
	}
	for name, call := range calls {
		agent := actingAs(starter, agentID)
		if err := call(authn.WithCaller(context.Background(), agent), agent); !refusedAsAgent(err) {
			t.Errorf("%s as the agent: err = %v", name, err)
		}
		if err := call(authn.WithCaller(context.Background(), starter), starter); err == nil || refusedAsAgent(err) {
			t.Errorf("%s as the starter: err = %v", name, err)
		}
	}
}

func TestOnlyAPersonApprovesAHeldCall(t *testing.T) {
	person := callerIn(t, uuid.NewString(), "user-1")
	agent := actingAs(person, "agent-1")
	named := []string{"user:user-1"}
	if !callerCanApprove(person, nil) || !callerCanApprove(person, named) || !mayResolve(person, nil, true) {
		t.Fatal("the starter may decide its run's escalations")
	}
	if callerCanApprove(agent, nil) || callerCanApprove(agent, named) || mayResolve(agent, nil, true) || mayResolve(agent, named, true) {
		t.Fatal("an agent decided an escalation as its starter")
	}
}

// Python lets a run act on what its starter started; Cancel, Pause and Retry keep that.
func TestAnAgentStillPausesARunItsStarterStarted(t *testing.T) {
	d := openDB(t)
	p, taskID := seed(t, d)
	s := NewSurface(SurfaceDeps{DB: d, Executor: &fakeExecutor{}, Log: quiet(), Now: fixedNow})
	agent := actingAs(callerIn(t, p.WorkspaceID, p.UserID), p.AgentID)
	if _, err := s.PlatformRuns().Pause(context.Background(), agent, taskID); err != nil {
		t.Fatalf("pause: %v", err)
	}
	if _, err := s.PlatformRuns().SendInput(context.Background(), agent, taskID, "q1", nil); !refusedAsAgent(err) {
		t.Fatalf("input: %v", err)
	}
}
