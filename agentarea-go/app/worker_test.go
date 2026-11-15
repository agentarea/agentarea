package app

import (
	"context"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/ext"
	runsservice "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/service"
)

type seenGuard struct{ got []ext.InterceptorContext }

func (*seenGuard) Name() string                      { return "plan" }
func (*seenGuard) Category() ext.InterceptorCategory { return ext.CategoryGate }
func (g *seenGuard) Execute(_ context.Context, ic ext.InterceptorContext) (ext.InterceptorResult, error) {
	g.got = append(g.got, ic)
	return ext.InterceptorResult{Action: ext.ActionDeny, InterceptorName: "plan", Reason: "over plan", Metadata: map[string]any{"entitlement_code": "x"}}, nil
}

func TestEntitlementGateCarriesTheResolvedModel(t *testing.T) {
	g := &seenGuard{}
	gate := entitlementGate{g: g}
	ctx := context.Background()
	call := runsservice.LLMGateCall{WorkspaceID: "ws", UserID: "u", AgentID: "a", ModelID: "m-1", ModelName: "gpt", ManagedBy: ext.ManagedByPlatform}
	r, err := gate.CheckLLMCall(ctx, call)
	if err != nil || r.Action != "deny" || r.InterceptorName != "plan" || r.Metadata["entitlement_code"] != "x" {
		t.Fatalf("%+v %v", r, err)
	}
	call.ManagedBy = ""
	if _, err := gate.CheckLLMCall(ctx, call); err != nil {
		t.Fatal(err)
	}
	platform, own := g.got[0], g.got[1]
	if platform.Phase != ext.PhasePreLLMCall || platform.ActionType != "llm_call" || platform.ActionName != "m-1" || platform.WorkspaceID != "ws" {
		t.Fatalf("%+v", platform)
	}
	if platform.Model == nil || *platform.Model != (ext.CallModel{ModelID: "m-1", ModelName: "gpt", ManagedBy: ext.ManagedByPlatform}) {
		t.Fatalf("platform-paid call: %+v", platform.Model)
	}
	if own.Model == nil || own.Model.ManagedBy != "" || own.Model.ModelID != "m-1" {
		t.Fatalf("customer key call: %+v", own.Model)
	}
	if _, err := gate.CheckLLMCall(ctx, runsservice.LLMGateCall{WorkspaceID: "ws"}); err != nil || g.got[2].Model != nil {
		t.Fatalf("unresolved model: %+v %v", g.got[2].Model, err)
	}
}
