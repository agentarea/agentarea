package service

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
	"image"
	"image/png"
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

func TestCallLLMLeavesOutAnImageTheProviderDoesNotTake(t *testing.T) {
	b := newMemBlob()
	p := testPrincipal()
	b.m[domain.ImageKey(p.WorkspaceID, "t1", "big")] = []byte("PNG")
	b.m[domain.ImageKey(p.WorkspaceID, "t1", "small")] = []byte("PNG")
	models := &fakeModels{reply: modelsapi.Reply{Usage: modelsapi.Usage{Total: 1}}}
	s := New(Deps{Blob: b, Pricing: eurPricing{}, Models: models, Log: quiet()})
	model := api.ResolvedModel{ModelID: "m", SupportsVision: true, Provider: modelsapi.ProviderProfile{MaxImageBytes: 5 << 20}}
	_, err := s.CallLLM(context.Background(), p, LLMCall{TaskID: "t1", Model: model, Policy: policy(), Pending: []domain.Entry{
		{Role: "assistant", ToolCalls: []domain.ToolCall{{ID: "c1", Name: "read_file"}}},
		{Role: "tool", ToolCallID: "c1", Name: "read_file", Content: "two", Attachments: []domain.ImageRef{
			{ID: "big", MimeType: "image/jpeg", Size: 12 << 20, Width: 4000, Height: 3000},
			{ID: "small", MimeType: "image/png", Size: 3},
		}},
	}})
	if err != nil {
		t.Fatal(err)
	}
	msgs := models.calls[0].Messages
	if len(msgs) != 3 || len(msgs[2].Parts) != 2 || msgs[2].Parts[1].ImageURL != "data:image/png;base64,UE5H" ||
		!strings.Contains(msgs[1].Content, "[image big not shown: 12.0 MB is over the 5.0 MB this model takes in one image;") {
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

func TestAMessageToAPersonGoesThroughThePolicyLikeAnyPlatformTool(t *testing.T) {
	tool := &fakeTool{out: ToolOutput{Success: true, Result: `{"sent":true}`}}
	s := New(Deps{Pricing: eurPricing{}, Tools: map[string]ToolCaller{"code": tool}, Log: quiet()})
	call := func(p api.Policy) ToolResult {
		t.Helper()
		out, err := s.ExecuteTool(context.Background(), testPrincipal(), ToolCall{
			TaskID: "t1", ToolName: "messages", Args: map[string]any{"text": "The report is ready"},
			Binding: api.ToolBinding{Source: "code", PolicyNames: []string{"agentarea/messages", "messages"},
				Code: &api.CodeBinding{Namespace: "agentarea/messages", Method: "send_message"}},
			Policy: p,
		})
		if err != nil {
			t.Fatal(err)
		}
		return out
	}
	if out := call(api.Policy{Tools: &api.ToolsPolicy{Denied: []string{"messages"}}}); out.Out.Success ||
		out.Out.Result != "Tool call denied by policy: tool 'messages' is denied by policy" {
		t.Fatalf("denied %+v", out)
	}
	if out := call(api.Policy{Approval: &api.ApprovalPolicy{EscalationRules: []string{"messages"}}}); out.Out.Success ||
		!strings.HasPrefix(out.Out.Error, "tool 'messages' requires approval") {
		t.Fatalf("held %+v", out)
	}
	if len(tool.calls) != 0 {
		t.Fatalf("sent despite the policy: %+v", tool.calls)
	}
	if out := call(api.Policy{}); !out.Out.Success || len(tool.calls) != 1 {
		t.Fatalf("allowed %+v", out)
	}
}

func TestExecuteToolOffloadsLargeOutputStoresImagesAndRelaysProgress(t *testing.T) {
	b, ev := newMemBlob(), &fakeEvents{}
	big := strings.Repeat("x", domain.OutputOffloadChars+1)
	shot := pngBytes(t, 6, 4)
	tool := &fakeTool{out: ToolOutput{Success: true, Result: big, Images: []ToolImage{{Data: shot, MimeType: "image/png"}, {Data: []byte("PNG"), MimeType: "image/png"}}}}
	s := New(Deps{Blob: b, Events: ev, Pricing: eurPricing{}, Tools: map[string]ToolCaller{"mcp": tool}, Log: quiet()})
	p := testPrincipal()
	out, err := s.ExecuteTool(context.Background(), p, ToolCall{
		TaskID: "t1", ToolCallID: "c1", ToolName: "search", ActivityID: "7", Attempt: 2,
		Binding: api.ToolBinding{Source: "mcp", MCP: &api.MCPBinding{InstanceID: "i1", RawName: "search"}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(out.Images) != 1 || out.Images[0] != (domain.ImageRef{ID: "mcp_tool_7_image_1", MimeType: "image/png", Size: int64(len(shot)), Width: 6, Height: 4}) ||
		!bytes.Equal(b.m[domain.ImageKey(p.WorkspaceID, "t1", "mcp_tool_7_image_1")], shot) {
		t.Fatalf("images %+v", out.Images)
	}
	if notes := string(b.m[domain.OutputKey(p.WorkspaceID, "t1", "mcp_tool_7")]); !strings.Contains(notes, "[image 2 not kept: image/png is not PNG, JPEG, GIF or WebP]") {
		t.Fatalf("a broken image was not named: %.200q", notes[len(notes)-120:])
	}
	stored := string(b.m[domain.OutputKey(p.WorkspaceID, "t1", "mcp_tool_7")])
	if !strings.HasPrefix(stored, big) || !strings.Contains(out.Out.Result, "mcp_tool_7") || out.Out.Result == big {
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

func TestReadFileShowsAnImageToTheModel(t *testing.T) {
	img := image.NewRGBA(image.Rect(0, 0, 3000, 1500))
	var b bytes.Buffer
	if err := png.Encode(&b, img); err != nil {
		t.Fatal(err)
	}
	rt := &fakeRuntime{files: map[string][]byte{"inputs/plan.png": b.Bytes(), "inputs/blob.bin": {0xff, 0xfe, 0x00},
		"inputs/plan.pdf": append([]byte("%PDF-1.7\n"), 0xff, 0xfe)}}
	s := New(Deps{Runtime: rt, Log: quiet()})
	read := func(name string) ToolOutput {
		t.Helper()
		in := ToolCall{TaskID: "t1", ToolName: "read_file", Args: map[string]any{"file_name": name},
			Binding: api.ToolBinding{Source: "code", Code: &api.CodeBinding{Namespace: "agentarea/files", Method: "read_file"}}}
		out, err := s.dispatch(context.Background(), testPrincipal(), in, nil)
		if err != nil {
			t.Fatal(err)
		}
		return out
	}
	out := read("inputs/plan.png")
	if !out.Success || len(out.Images) != 1 || out.Images[0].MimeType != "image/png" {
		t.Fatalf("%+v", out)
	}
	if want := fmt.Sprintf("inputs/plan.png is an image (image/png, 3000x1500 px, %d KB); it is attached.", (b.Len()+1023)/1024); out.Result != want || !bytes.Equal(out.Images[0].Data, b.Bytes()) {
		t.Fatalf("result %q, want %q", out.Result, want)
	}
	if out := read("inputs/blob.bin"); len(out.Images) != 0 || !strings.Contains(out.Result, "can't decode") {
		t.Fatalf("binary %+v", out)
	}
	if out := read("inputs/plan.pdf"); len(out.Images) != 0 || !strings.HasPrefix(out.Result, "Error reading file: inputs/plan.pdf: not a readable PDF:") {
		t.Fatalf("broken pdf %+v", out)
	}
}

func TestReadFileReadsPDFPages(t *testing.T) {
	rt := &fakeRuntime{files: map[string][]byte{"inputs/short.pdf": pdfOf(4), "inputs/plan.pdf": pdfOf(42), "notes.txt": []byte("a\nb\nc\nd\ne")}}
	s := New(Deps{Runtime: rt, Log: quiet()})
	read := func(args map[string]any) ToolOutput {
		t.Helper()
		in := ToolCall{TaskID: "t1", ToolName: "read_file", Args: args,
			Binding: api.ToolBinding{Source: "code", Code: &api.CodeBinding{Namespace: "agentarea/files", Method: "read_file"}}}
		out, err := s.dispatch(context.Background(), testPrincipal(), in, nil)
		if err != nil {
			t.Fatal(err)
		}
		return out
	}
	out := read(map[string]any{"file_name": "inputs/short.pdf"})
	if len(out.Images) != 1 || out.Images[0].MimeType != "application/pdf" || out.Images[0].Pages != 4 ||
		out.Result != "inputs/short.pdf: pages 1-4 of 4 (PDF); it is attached." {
		t.Fatalf("short %+v", out)
	}
	if out := read(map[string]any{"file_name": "inputs/plan.pdf"}); len(out.Images) != 0 ||
		out.Result != "inputs/plan.pdf has 42 pages; read up to 20 at a time with pages, e.g. pages: \"1-5\"." {
		t.Fatalf("long without pages %+v", out)
	}
	out = read(map[string]any{"file_name": "inputs/plan.pdf", "pages": "3-5"})
	if len(out.Images) != 1 || out.Images[0].Pages != 3 || out.Result != "inputs/plan.pdf: pages 3-5 of 42 (PDF); it is attached." {
		t.Fatalf("pages %+v", out)
	}
	for args, want := range map[string]string{
		"1-21":  "Error reading file: inputs/plan.pdf: pages 1-21 is 21 pages; read up to 20 at a time",
		"40-45": "Error reading file: inputs/plan.pdf: pages 40-45 is past the last page, 42",
	} {
		if out := read(map[string]any{"file_name": "inputs/plan.pdf", "pages": args}); out.Result != want || len(out.Images) != 0 {
			t.Fatalf("pages %s: %q", args, out.Result)
		}
	}
	if out := read(map[string]any{"file_name": "notes.txt", "pages": "1"}); out.Result != "Error reading file: notes.txt: pages is for PDF files" {
		t.Fatalf("pages on text %q", out.Result)
	}
	if out := read(map[string]any{"file_name": "notes.txt", "offset": float64(2), "limit": float64(2)}); out.Result != "b\nc\n[lines 2-3 of 5; read on with offset: 4]" {
		t.Fatalf("offset %q", out.Result)
	}
	if out := read(map[string]any{"file_name": "notes.txt", "offset": float64(4)}); out.Result != "d\ne" {
		t.Fatalf("offset to the end %q", out.Result)
	}
	if out := read(map[string]any{"file_name": "notes.txt", "offset": float64(9)}); out.Result != "Error reading file: notes.txt: offset 9 is past the last line, 5" {
		t.Fatalf("offset past the end %q", out.Result)
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
