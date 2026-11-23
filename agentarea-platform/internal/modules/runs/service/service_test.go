package service

import (
	"context"
	"errors"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

func intp(n int) *int { return &n }

func dec(s string) *money.Decimal {
	d := money.MustParse(s)
	return &d
}

func policy() api.Policy { return api.Policy{Tokens: &api.TokenPolicy{MaxTokensPerCall: intp(1000)}} }

func platformModel() api.ResolvedModel {
	return api.ResolvedModel{
		ModelID: "5a8e0f8c-7f0e-4b8e-9d55-0d6a9b2a1c11", ModelName: "m", ManagedBy: "platform", MaxOutputTokens: intp(200),
		Prices: api.ModelPrices{Input: dec("0.000001"), Output: dec("0.000002")},
	}
}

func appErr(t *testing.T, err error) *durable.ApplicationError {
	t.Helper()
	var app *durable.ApplicationError
	if !errors.As(err, &app) {
		t.Fatalf("error %v is not an ApplicationError", err)
	}
	return app
}

func TestCallLLMHoldsAPlatformCallAndChargesBillingsQuote(t *testing.T) {
	ev, bill := &fakeEvents{}, &fakeBilling{hold: money.HoldDecision{Allowed: true, HoldID: "h1", Amount: dec("2"), Currency: "EUR"}, quote: dec("1.5")}
	models := &fakeModels{reply: modelsapi.Reply{Content: "hello", Usage: modelsapi.Usage{Prompt: 4, Completion: 6, Total: 10}, ProviderCostUSD: money.MustParse("0.01"), ChunkCount: 2}}
	s := New(Deps{Events: ev, Billing: bill, Pricing: eurPricing{}, Models: models, Log: quiet(), Now: fixedNow})
	out, err := s.CallLLM(context.Background(), testPrincipal(), LLMCall{
		TaskID: "t1", ExecutionID: "e1", Iteration: 3, Model: platformModel(), StreamText: true, Policy: policy(),
		Pending: []domain.Entry{{Role: "user", Content: "hi"}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if out.Cost.String() != "1.5" || out.Currency != "EUR" || out.Billing.HoldID != "h1" || out.Billing.Settle != "capture" || !out.Billing.PlatformFunded || out.Billing.VendorCurrency != "USD" {
		t.Fatalf("result %+v", out)
	}
	call := models.calls[0]
	if len(call.Messages) != 1 || call.MaxTokens != 200 || !call.Funded {
		t.Fatalf("model call %+v", call)
	}
	if len(bill.authed) != 1 || bill.authed[0].Kind != money.KindModel || !strings.HasPrefix(bill.authed[0].IdempotencyKey, "llm:t1:") {
		t.Fatalf("authorize %+v", bill.authed)
	}
	last := ev.broadcast[len(ev.broadcast)-1].Data
	if last["is_final"] != true || last["chunk"] != "hello" || last["thinking"] != "thinking" || last["iteration"] != 3 {
		t.Fatalf("final chunk %+v", last)
	}
}

func TestCallLLMRefusedByBillingIsAGateVerdict(t *testing.T) {
	bill := &fakeBilling{hold: money.HoldDecision{Code: "no_credits", Reason: "the balance is empty"}}
	s := New(Deps{Billing: bill, Pricing: eurPricing{}, Models: &fakeModels{}, Log: quiet()})
	_, err := s.CallLLM(context.Background(), testPrincipal(), LLMCall{TaskID: "t1", Model: platformModel(), Policy: policy()})
	app := appErr(t, err)
	if app.Type != "GovernanceDeniedError" || !app.NonRetryable || app.Message != "billing: the balance is empty" {
		t.Fatalf("error %+v", app)
	}
	details := app.Details[0].(map[string]any)
	if details["phase"] != "pre_llm_call" || details["metadata"].(map[string]any)["entitlement_code"] != "no_credits" {
		t.Fatalf("details %+v", details)
	}
}

func TestCallLLMVoidsTheHoldOfAFailedCall(t *testing.T) {
	bill := &fakeBilling{hold: money.HoldDecision{Allowed: true, HoldID: "h1", Amount: dec("2"), Currency: "EUR"}}
	s := New(Deps{Billing: bill, Pricing: eurPricing{}, Models: &fakeModels{err: errors.New("connection reset")}, Log: quiet()})
	_, err := s.CallLLM(context.Background(), testPrincipal(), LLMCall{TaskID: "t1", Model: platformModel(), Policy: policy()})
	app := appErr(t, err)
	if app.NonRetryable || app.Message != "LLM call failed: connection reset" || len(bill.voided) != 1 {
		t.Fatalf("error %+v voided %v", app, bill.voided)
	}
}

func TestCallLLMNeedsThePerCallTokenLimit(t *testing.T) {
	s := New(Deps{Pricing: eurPricing{}, Models: &fakeModels{}, Log: quiet()})
	_, err := s.CallLLM(context.Background(), testPrincipal(), LLMCall{Model: api.ResolvedModel{ModelID: "m"}})
	if app := appErr(t, err); app.Type != "ValueError" || !app.NonRetryable {
		t.Fatalf("error %+v", app)
	}
}

func TestCallLLMShowsStoredToolImagesToAVisionModel(t *testing.T) {
	b := newMemBlob()
	p := testPrincipal()
	b.m[domain.ImageKey(p.WorkspaceID, "t1", "out_image_1")] = []byte("PNG")
	models := &fakeModels{reply: modelsapi.Reply{Usage: modelsapi.Usage{Total: 1}}}
	s := New(Deps{Blob: b, Pricing: eurPricing{}, Models: models, Log: quiet()})
	model := api.ResolvedModel{ModelID: "m", SupportsVision: true}
	_, err := s.CallLLM(context.Background(), p, LLMCall{TaskID: "t1", Model: model, Policy: policy(), Pending: []domain.Entry{
		{Role: "assistant", ToolCalls: []domain.ToolCall{{ID: "c1", Name: "shot"}}},
		{Role: "tool", ToolCallID: "c1", Name: "shot", Content: "took it", Attachments: []domain.ImageRef{{ID: "out_image_1", MimeType: "image/png"}}},
	}})
	if err != nil {
		t.Fatal(err)
	}
	msgs := models.calls[0].Messages
	if len(msgs) != 3 || msgs[2].Role != "user" || msgs[2].Parts[1].ImageURL != "data:image/png;base64,UE5H" {
		t.Fatalf("messages %+v", msgs)
	}
}

func TestExecuteToolDeniedByPolicyIsAnswered(t *testing.T) {
	tool := &fakeTool{}
	s := New(Deps{Pricing: eurPricing{}, Tools: map[string]ToolCaller{"code": tool}, Log: quiet()})
	out, err := s.ExecuteTool(context.Background(), testPrincipal(), ToolCall{
		TaskID: "t1", ToolName: "bash", Binding: api.ToolBinding{Source: "code"},
		Policy: api.Policy{Tools: &api.ToolsPolicy{Denied: []string{"ba*"}}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if out.Out.Success || out.Out.Result != "Tool call denied by policy: tool 'bash' is denied by policy" || len(tool.calls) != 0 {
		t.Fatalf("result %+v", out)
	}
}

func TestExecuteToolHeldForApprovalUntilGranted(t *testing.T) {
	tool := &fakeTool{out: ToolOutput{Success: true, Result: "ok"}}
	s := New(Deps{Pricing: eurPricing{}, Tools: map[string]ToolCaller{"code": tool}, Log: quiet()})
	yes := true
	call := ToolCall{TaskID: "t1", ToolName: "bash", Binding: api.ToolBinding{Source: "code"},
		Policy: api.Policy{Approval: &api.ApprovalPolicy{RequiresHumanApproval: &yes}}}
	out, _ := s.ExecuteTool(context.Background(), testPrincipal(), call)
	if !strings.HasSuffix(out.Out.Error, "; approval must be resolved before activity execution") {
		t.Fatalf("held result %+v", out)
	}
	call.PolicyApprovalGranted = true
	out, err := s.ExecuteTool(context.Background(), testPrincipal(), call)
	if err != nil || !out.Out.Success || len(tool.calls) != 1 {
		t.Fatalf("granted result %+v %v", out, err)
	}
}

func TestExecuteToolOffloadsLargeOutputStoresImagesAndRelaysProgress(t *testing.T) {
	b, ev := newMemBlob(), &fakeEvents{}
	big := strings.Repeat("x", domain.OutputOffloadChars+1)
	tool := &fakeTool{out: ToolOutput{Success: true, Result: big, Images: []ToolImage{{Data: []byte("PNG"), MimeType: "image/png"}}}}
	s := New(Deps{Blob: b, Events: ev, Pricing: eurPricing{}, Tools: map[string]ToolCaller{"mcp": tool}, Log: quiet()})
	p := testPrincipal()
	out, err := s.ExecuteTool(context.Background(), p, ToolCall{
		TaskID: "t1", ToolCallID: "c1", ToolName: "search", ActivityID: "7", Attempt: 2,
		Binding: api.ToolBinding{Source: "mcp", MCP: &api.MCPBinding{InstanceID: "i1", RawName: "search"}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(out.Images) != 1 || out.Images[0].ID != "mcp_tool_7_image_1" || string(b.m[domain.ImageKey(p.WorkspaceID, "t1", "mcp_tool_7_image_1")]) != "PNG" {
		t.Fatalf("images %+v", out.Images)
	}
	stored := string(b.m[domain.OutputKey(p.WorkspaceID, "t1", "mcp_tool_7")])
	if stored != big || !strings.Contains(out.Out.Result, "mcp_tool_7") || out.Out.Result == big {
		t.Fatalf("offload: stored %d chars, result %.80q", len(stored), out.Out.Result)
	}
	if out.Attempt == nil || *out.Attempt != 2 || out.Payer != "workspace" {
		t.Fatalf("result %+v", out)
	}
	if len(ev.broadcast) != 1 || ev.broadcast[0].Type != domain.EventToolProgress || ev.broadcast[0].Data["message"] != "done" {
		t.Fatalf("progress %+v", ev.broadcast)
	}
	if tool.calls[0].CallRef != "t1:c1" {
		t.Fatalf("call ref %q", tool.calls[0].CallRef)
	}
}

func TestExecuteToolOnThePlatformsKeyIsRefusedWithoutAHold(t *testing.T) {
	bill := &fakeBilling{hold: money.HoldDecision{Code: "credit_limit_reached", Reason: "limit"}}
	tool := &fakeTool{out: ToolOutput{Success: true}}
	s := New(Deps{Billing: bill, Pricing: eurPricing{}, Tools: map[string]ToolCaller{"openapi": tool}, Log: quiet()})
	out, err := s.ExecuteTool(context.Background(), testPrincipal(), ToolCall{
		TaskID: "t1", ToolCallID: "c1", ToolName: "op",
		Binding: api.ToolBinding{Source: "openapi", OpenAPI: &api.OpenAPIBinding{ConnectionID: "k1", OperationID: "op"},
			Cost: &api.ToolCost{Payer: "platform", Connector: "acme", VendorCost: money.MustParse("0.2"), VendorCurrency: "USD"}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if out.Out.Error != "credit_limit_reached: limit" || len(tool.calls) != 0 || bill.authed[0].Kind != money.KindTool {
		t.Fatalf("result %+v", out)
	}
}

func TestToolSpendCapsNameAndNarrowEachCap(t *testing.T) {
	budget := &api.BudgetPolicy{
		MonthlySpendCap: dec("10"), RunBudget: dec("1"),
		SpendCaps: []api.SpendCap{
			{Amount: money.MustParse("5"), Category: "llm"},
			{Amount: money.MustParse("3"), Category: "tools"},
			{Amount: money.MustParse("2"), Tool: "search", Period: "run"},
			{Amount: money.MustParse("2"), ConnectionID: "other"},
		},
	}
	caps := toolSpendCaps(budget, toolCallScope{TaskID: "t1", AgentID: "a1", HasConnection: true, ConnectionID: "i1", Tool: "search"}, "EUR")
	var labels []string
	for _, c := range caps {
		labels = append(labels, c.Label)
	}
	if strings.Join(labels, ",") != "workspace monthly,run,monthly tools,run tool" {
		t.Fatalf("caps %v", labels)
	}
	if got := caps[0].refusal(money.MustParse("9.50"), dec("1.00")); got != "workspace monthly spend cap of 10 EUR would be exceeded: 9.5 EUR spent this month, this call costs 1 EUR" {
		t.Fatalf("refusal %q", got)
	}
	if got := caps[1].refusal(money.MustParse("1"), nil); got != "run spend cap of 1 EUR reached: 1 EUR spent in this run" {
		t.Fatalf("refusal %q", got)
	}
}

func TestDeliverToRunnerSendsWhatIsSet(t *testing.T) {
	ev := &fakeEvents{}
	s := New(Deps{Events: ev, Log: quiet()})
	no := false
	if err := s.DeliverToRunner(context.Background(), RunnerDelivery{ClientID: "c1", TaskID: "t1", Kind: "decision", RequestID: "r1", Approved: &no}); err != nil {
		t.Fatal(err)
	}
	got := ev.runner[0]
	if got["client"] != "c1" || got["approved"] != "false" || got["kind"] != "decision" || got["request_id"] != "r1" || len(got) != 5 {
		t.Fatalf("fields %+v", got)
	}
}

func TestValidateArtifactsFailsClosed(t *testing.T) {
	for in, want := range map[string]string{"passed": "failed", "weird": "unavailable"} {
		rt := &fakeRuntime{validation: sandboxapi.ArtifactValidation{State: in, Issues: []sandboxapi.ArtifactIssue{{Code: "x"}}}}
		s := New(Deps{Runtime: rt, Log: quiet()})
		v, err := s.ValidateArtifacts(context.Background(), testPrincipal(), "t1", nil)
		if err != nil || v.State != want {
			t.Fatalf("%s: %+v %v", in, v, err)
		}
	}
}

func TestStoreAndReadOutputThroughTheContextStore(t *testing.T) {
	s := New(Deps{Blob: newMemBlob(), Log: quiet()})
	p := testPrincipal()
	if err := s.StoreOutput(context.Background(), p, "t1", "o1", "alpha\nbeta\ngamma"); err != nil {
		t.Fatal(err)
	}
	got, err := s.ReadOutput(context.Background(), p, "t1", "o1", "beta", nil, nil)
	if err != nil || !strings.Contains(got, "beta") || strings.Contains(got, "alpha") {
		t.Fatalf("read %q %v", got, err)
	}
	if err := s.StoreOutput(context.Background(), Principal{}, "t1", "o1", "x"); appErr(t, err).Type != "ValueError" {
		t.Fatal("an incomplete principal was accepted")
	}
}

func TestFileToolsRunInTheSandbox(t *testing.T) {
	rt := &fakeRuntime{files: map[string][]byte{}}
	s := New(Deps{Runtime: rt, Log: quiet()})
	call := func(method string, args map[string]any) string {
		t.Helper()
		in := ToolCall{TaskID: "t1", ToolName: method, Args: args, Binding: api.ToolBinding{Source: "code", Code: &api.CodeBinding{Namespace: "agentarea/files", Method: method}}}
		out, err := s.dispatch(context.Background(), testPrincipal(), in, nil)
		if err != nil || !out.Success {
			t.Fatalf("%s: %+v %v", method, out, err)
		}
		return out.Result
	}
	if got := call("save_file", map[string]any{"contents": "hi", "file_name": "outputs/a.md"}); got != "outputs/a.md" {
		t.Fatalf("save %q", got)
	}
	if got := call("save_file", map[string]any{"contents": "x", "file_name": "outputs/a.md", "overwrite": false}); got != "File outputs/a.md already exists" {
		t.Fatalf("no overwrite %q", got)
	}
	if got := call("save_file", map[string]any{"contents": "x", "file_name": "r.PDF"}); !strings.HasPrefix(got, "Error: save_file writes UTF-8 text only and would corrupt a .pdf file.") {
		t.Fatalf("binary %q", got)
	}
	if got := call("save_file", map[string]any{"contents": "x", "file_name": "../x"}); got != "Error saving to file: path escapes workspace sandbox: '../x'" {
		t.Fatalf("escape %q", got)
	}
	if got := call("read_file", map[string]any{"file_name": "outputs/a.md"}); got != "hi" {
		t.Fatalf("read %q", got)
	}
	if got := call("read_file", map[string]any{"file_name": "nope"}); got != "Error: File nope does not exist" {
		t.Fatalf("missing %q", got)
	}
	want := "{\n  \"scope\": \"/\",\n  \"pattern\": \"*.md\",\n  \"files_found\": 1,\n  \"files\": [\n    \"outputs/a.md\"\n  ]\n}"
	if got := call("list_files", map[string]any{"pattern": "*.md"}); got != want {
		t.Fatalf("list %s", got)
	}
	if got := call("search_files", map[string]any{"pattern": " "}); got != "Error: Pattern cannot be empty" {
		t.Fatalf("search %q", got)
	}
}

func TestBashGoesToTheSandboxWithTheRunsProject(t *testing.T) {
	rt := &fakeRuntime{}
	s := New(Deps{Runtime: rt, Log: quiet()})
	in := ToolCall{TaskID: "t1", WorkflowID: "wf", ToolName: "bash", Args: map[string]any{"command": "ls", "timeout_seconds": float64(5)},
		RunMetadata: map[string]any{"project_id": "p1"}, Binding: api.ToolBinding{Source: "code", Code: &api.CodeBinding{Namespace: "agentarea/shell", Method: "bash"}}}
	out, err := s.dispatch(context.Background(), testPrincipal(), in, nil)
	if err != nil || out.Result != "ran ls" || out.Source != "builtin" {
		t.Fatalf("%+v %v", out, err)
	}
	b := rt.bash[0]
	if b.WorkflowID != "wf" || b.ProjectID != "p1" || *b.TimeoutSeconds != 5 || b.TaskID != "t1" {
		t.Fatalf("call %+v", b)
	}
}
