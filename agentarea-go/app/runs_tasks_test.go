package app

import (
	"context"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams"
)

type standingRows struct {
	status map[string]string
	saved  map[string]agentsapi.TaskDef
}

func (s standingRows) AgentStatus(_ context.Context, _ scope.Workspace, id string) (string, bool, error) {
	st, ok := s.status[id]
	return st, ok, nil
}

func (s standingRows) TaskDefinition(_ context.Context, _ scope.Workspace, id string) (agentsapi.TaskDef, bool, error) {
	d, ok := s.saved[id]
	return d, ok, nil
}

type costRows map[string]float64

func (costRows) Statuses(context.Context, scope.Workspace, []string) (map[string]string, error) {
	return nil, nil
}

func (c costRows) Costs(context.Context, scope.Workspace, []string) (map[string]float64, error) {
	return c, nil
}

func TestStreamsSeesAnArchivedAgentAsGone(t *testing.T) {
	a := streamsAgents{standingRows{status: map[string]string{"a": agentsapi.StatusActive, "b": agentsapi.StatusArchived}}}
	for id, want := range map[string]bool{"a": true, "b": false, "c": false} {
		if got, err := a.AgentExists(context.Background(), scope.Workspace{}, id); err != nil || got != want {
			t.Errorf("%s: %v %v", id, got, err)
		}
	}
}

func TestStreamsTaskPortsMapRunsAndAgents(t *testing.T) {
	ctx := context.Background()
	costs, err := streamsTaskReads{costRows{"t1": 0.5, "t2": 0}}.Costs(ctx, scope.Workspace{}, []string{"t1", "t2"})
	if err != nil || len(costs) != 2 || *costs["t1"].CostUSD != 0.5 || *costs["t2"].CostUSD != 0 {
		t.Fatalf("%v %v", costs, err)
	}
	f := streamsFiringTasks{saved: standingRows{saved: map[string]agentsapi.TaskDef{
		"d1": {Description: "ask", Parameters: []byte(`{"k": [1]}`)},
		"d2": {Description: "bare", Parameters: []byte(`null`)},
	}}}
	d, ok, err := f.Definition(ctx, scope.Workspace{}, "d1")
	if err != nil || !ok || d.Description != "ask" || len(d.Parameters["k"].([]any)) != 1 {
		t.Fatalf("%+v %v %v", d, ok, err)
	}
	if d, ok, _ := f.Definition(ctx, scope.Workspace{}, "d2"); !ok || d.Parameters == nil || len(d.Parameters) != 0 {
		t.Fatalf("%+v", d)
	}
	if _, ok, err := f.Definition(ctx, scope.Workspace{}, "gone"); ok || err != nil {
		t.Fatalf("%v %v", ok, err)
	}
}

var _ runsapi.TaskReads = costRows{}

func TestTheEventsRoleGetsEveryPortItFiresThrough(t *testing.T) {
	agentsMod := agents.New(agents.Deps{})
	r := newRunsSurface(nil, coreDeps{}, runsProviders{Agents: agentsMod, Governance: governance.New(governance.Deps{})})
	var sd streams.Deps
	streamsRunsPorts(&sd, r, agentsMod)
	if missing := eventsMissing(sd); len(missing) != 1 || missing[0] != "sandbox processor runner (sandbox)" || sd.Agents == nil || sd.TaskReads == nil {
		t.Fatalf("missing %v", missing)
	}
}
