package service

import (
	"context"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/domain"
)

type transition struct {
	status, reason string
	elapsed        *time.Duration
}

type fakeTelemetry struct{ got []transition }

func (f *fakeTelemetry) RunTransition(status, reason string, elapsed *time.Duration) {
	f.got = append(f.got, transition{status, reason, elapsed})
}

func TestRunTransitionCountsTheClosedReasonAndTheDuration(t *testing.T) {
	tel := &fakeTelemetry{}
	s := New(Deps{Telemetry: tel, Now: fixedNow, Log: quiet()})
	started := fixedNow().Add(-90 * time.Second)
	s.recordRunTransition(domain.StatusUpdate{Status: "failed", FailureReason: "rate_limited", RunStartedAt: &started})
	s.recordRunTransition(domain.StatusUpdate{Status: "running", RunStartedAt: &started})
	s.recordRunTransition(domain.StatusUpdate{Status: "blocked", FailureReason: "some_rule"})
	if len(tel.got) != 3 || tel.got[0].reason != "provider" || tel.got[0].elapsed == nil || *tel.got[0].elapsed != 90*time.Second {
		t.Fatalf("transitions %+v", tel.got)
	}
	if tel.got[1].reason != "none" || tel.got[1].elapsed != nil || tel.got[2].reason != "policy" {
		t.Fatalf("transitions %+v", tel.got)
	}
	New(Deps{Log: quiet()}).recordRunTransition(domain.StatusUpdate{Status: "failed"})
}

type fakeGate struct {
	calls []LLMGateCall
	res   GateResult
}

func (f *fakeGate) CheckLLMCall(_ context.Context, c LLMGateCall) (GateResult, error) {
	f.calls = append(f.calls, c)
	return f.res, nil
}

func TestEntitlementGateSeesTheResolvedModelAndItsPayer(t *testing.T) {
	gate := &fakeGate{res: GateResult{Action: "allow"}}
	models := &fakeModels{}
	models.reply.Usage.Total = 1
	s := New(Deps{Entitlement: gate, Pricing: eurPricing{}, Models: models, Log: quiet()})
	own := api.ResolvedModel{ModelID: "m-own", ModelName: "own"}
	for _, m := range []api.ResolvedModel{platformModel(), own} {
		if _, err := s.CallLLM(context.Background(), testPrincipal(), LLMCall{TaskID: "t1", Model: m, Policy: policy()}); err != nil {
			t.Fatal(err)
		}
	}
	if gate.calls[0].ManagedBy != "platform" || gate.calls[0].ModelID != platformModel().ModelID || gate.calls[1].ManagedBy != "" || gate.calls[1].ModelName != "own" {
		t.Fatalf("gate calls %+v", gate.calls)
	}
	if gate.calls[0].ExecutionState["max_tokens_per_call"] != 1000 || gate.calls[0].WorkspaceID != testPrincipal().WorkspaceID {
		t.Fatalf("gate call %+v", gate.calls[0])
	}
}

func TestEntitlementDenialIsAGateVerdictBeforeTheHold(t *testing.T) {
	gate := &fakeGate{res: GateResult{Action: "deny", InterceptorName: "plan_entitlement", Reason: "model not in plan", Metadata: map[string]any{"entitlement_code": "model_not_in_plan"}}}
	bill := &fakeBilling{}
	s := New(Deps{Entitlement: gate, Billing: bill, Pricing: eurPricing{}, Models: &fakeModels{}, Log: quiet()})
	_, err := s.CallLLM(context.Background(), testPrincipal(), LLMCall{TaskID: "t1", Model: platformModel(), Policy: policy()})
	app := appErr(t, err)
	if app.Type != "GovernanceDeniedError" || !app.NonRetryable || app.Message != "plan_entitlement: model not in plan" || len(bill.authed) != 0 {
		t.Fatalf("error %+v authed %v", app, bill.authed)
	}
	details := app.Details[0].(map[string]any)
	if details["interceptor_name"] != "plan_entitlement" || details["metadata"].(map[string]any)["entitlement_code"] != "model_not_in_plan" {
		t.Fatalf("details %+v", details)
	}
}
