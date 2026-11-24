package service

import (
	"context"
	"encoding/json"
	"slices"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

type recordedClientCalls struct {
	calls   []runsapi.ClientToolCall
	refusal string
}

func (r *recordedClientCalls) RunClientCall(_ context.Context, _ scope.Workspace, call runsapi.ClientToolCall, _ runsapi.ClientCallHooks) (string, error) {
	r.calls = append(r.calls, call)
	return r.refusal, nil
}

func TestARunnerTurnsCallGoesToItsRunWithThePolicyNames(t *testing.T) {
	calls := &recordedClientCalls{refusal: "run spend cap of 0.5 EUR would be exceeded"}
	s := &Service{d: Deps{ClientCalls: calls}}
	c := authn.Caller{Principal: authn.Principal{UserID: "u1", BoundTaskID: "task-1", TurnClientID: "client-1"}}
	names := governanceapi.ToolNames{Aliases: []string{"mcp:i1:search"}, Restricting: []string{"acme:search", "search"}}
	allow := governanceapi.ToolDecision{Action: governanceapi.ToolAllow}
	ran := false
	_, refused, err := s.judged(context.Background(), c, "client-1",
		toolAudit{name: "acme__search", args: json.RawMessage(`{"q":"x"}`)}, allow, nil,
		named(mcpBinding("i1", "search"), names), func() (any, error) { ran = true; return nil, nil })
	if err != nil || refused != "Tool call refused: run spend cap of 0.5 EUR would be exceeded" || ran {
		t.Fatalf("refused %q err %v ran %v", refused, err, ran)
	}
	if len(calls.calls) != 1 {
		t.Fatalf("calls %+v", calls.calls)
	}
	got := calls.calls[0]
	if got.TaskID != "task-1" || got.ClientID != "client-1" || got.Approved ||
		!slices.Equal(got.Binding.PolicyNames, names.Aliases) || !slices.Equal(got.Binding.RestrictingNames, names.Restricting) {
		t.Fatalf("call %+v", got)
	}

	unwired := &Service{}
	if _, _, err := unwired.judged(context.Background(), c, "client-1", toolAudit{name: "acme__search"}, allow, nil,
		mcpBinding("i1", "search"), func() (any, error) { ran = true; return nil, nil }); err == nil || ran {
		t.Fatalf("a runner turn's call ran without its run's layer: %v ran %v", err, ran)
	}
}
