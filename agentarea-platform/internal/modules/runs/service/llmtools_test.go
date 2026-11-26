package service

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

const (
	llmFlash = "6f1d7c2a-0b7e-4a52-9d61-0d7c2f9b1a01"
	llmArgon = "6f1d7c2a-0b7e-4a52-9d61-0d7c2f9b1a02"
	llmS1    = "6f1d7c2a-0b7e-4a52-9d61-0d7c2f9b1a03"
	llmGone  = "6f1d7c2a-0b7e-4a52-9d61-0d7c2f9b1a04"
)

type llmNames map[string]modelsapi.InstanceName

func (n llmNames) InstanceName(_ context.Context, _ scope.Workspace, id string) (modelsapi.InstanceName, bool, error) {
	m, ok := n[id]
	return m, ok, nil
}

type llmResolver map[string]modelsapi.ResolvedModel

func (r llmResolver) Model(_ context.Context, _ modelsapi.Principal, id string) (modelsapi.ResolvedModel, error) {
	m, ok := r[id]
	if !ok {
		return modelsapi.ResolvedModel{}, modelsapi.ErrNotFound
	}
	return m, nil
}

type llmFixture struct {
	s       *Service
	models  *fakeModels
	rt      *fakeRuntime
	bill    *fakeBilling
	decided modelsapi.Decision
}

func newLLMFixture(t *testing.T, reply string) *llmFixture {
	t.Helper()
	price := money.MustParse("0.000001")
	held := money.MustParse("1")
	f := &llmFixture{
		models: &fakeModels{reply: modelsapi.Reply{Content: reply, Usage: modelsapi.Usage{Total: 10}, ProviderCostUSD: money.MustParse("0.002")}},
		rt:     &fakeRuntime{files: map[string][]byte{}},
		bill:   &fakeBilling{hold: money.HoldDecision{Allowed: true, HoldID: "h1", Amount: &held, Currency: "EUR"}, quote: &held},
	}
	f.s = New(Deps{
		Pricing: eurPricing{}, Billing: f.bill, Models: f.models, Runtime: f.rt, Log: quiet(),
		ModelNames: llmNames{
			llmFlash: {ID: llmFlash, Name: "flash", ModelName: "gemini-3.8-flash", Kind: modelsapi.KindChat},
			llmArgon: {ID: llmArgon, Name: "argon", ModelName: "gemini-4-argon", Kind: modelsapi.KindChat},
			llmS1:    {ID: llmS1, Name: "s1", ModelName: "system-one", Kind: modelsapi.KindDecision},
		},
		Resolver: llmResolver{
			llmFlash: {ModelID: llmFlash, ModelName: "gemini-3.8-flash", ManagedBy: "platform", SupportsVision: true,
				Prices: modelsapi.ModelPrices{Input: &price, Output: &price}, ReasoningLevels: []string{"low", "high"},
				Provider: modelsapi.ProviderProfile{PDFInput: true, MaxImageEdge: 2000}},
			llmArgon: {ModelID: llmArgon, ModelName: "gemini-4-argon", Prices: modelsapi.ModelPrices{Input: &price, Output: &price}},
		},
		Describer: describedModels{llmS1: {ModelID: llmS1, ModelName: "system-one", DisplayName: modelsapi.KindDecision, SupportsVision: true}},
		Decider: fakeDecider{got: &f.decided, reply: modelsapi.DecisionReply{Answers: map[string]map[string]any{
			"q": {"type": "choice", "choice": "yes"}}, CostUSD: &price}},
	})
	return f
}

func llmInvocation(method string, args map[string]any, models ...api.ToolModel) ToolInvocation {
	if models == nil {
		models = []api.ToolModel{{ModelID: llmFlash}, {ModelID: llmArgon}, {ModelID: llmS1}, {ModelID: llmGone}}
	}
	return ToolInvocation{Principal: testPrincipal(), TaskID: "task-1", CallRef: "call-1", ToolName: "llm_" + method, Args: args,
		Binding: api.ToolBinding{Source: "code", Code: &api.CodeBinding{Namespace: llmToolset, Method: method, Models: models}}}
}

func llmTokens(n int) api.Policy { return api.Policy{Tokens: &api.TokenPolicy{MaxTokensPerCall: &n}} }

func (f *llmFixture) call(t *testing.T, policy api.Policy, inv ToolInvocation) ToolOutput {
	t.Helper()
	caller := f.s.llmCaller(ToolCall{Binding: inv.Binding, Policy: policy})
	if caller == nil {
		t.Fatal("agentarea/llm has no caller")
	}
	out, err := caller.Call(context.Background(), inv)
	if err != nil {
		t.Fatalf("call raised %v", err)
	}
	return out
}

func TestLLMCallAnswersWithTheModelNamedAndChargesIt(t *testing.T) {
	f := newLLMFixture(t, "  the answer  ")
	out := f.call(t, llmTokens(1000), llmInvocation("call", map[string]any{"model": "gemini-3.8-flash", "prompt": "hi", "system": "be brief"}))
	if !out.Success || out.Result != "the answer" || out.ModelBilling == nil || out.ModelBilling.HoldID != "h1" || out.ModelCost.String() != "1" {
		t.Fatalf("out = %+v", out)
	}
	c := f.models.calls[0]
	if c.Model.ModelID != llmFlash || !c.Funded || c.MaxTokens != 1000 || len(c.Tools) != 0 || len(c.Messages) != 2 ||
		c.Messages[0].Role != "system" || c.Messages[0].Content != "be brief" || c.Messages[1].Content != "hi" {
		t.Fatalf("call = %+v", c)
	}
	if len(f.bill.authed) != 1 {
		t.Fatalf("holds = %+v", f.bill.authed)
	}
	for _, ref := range []string{"flash", llmFlash} {
		if out := f.call(t, llmTokens(1000), llmInvocation("call", map[string]any{"model": ref, "prompt": "hi"})); !out.Success {
			t.Fatalf("%s: %+v", ref, out)
		}
	}
}

func TestLLMCallRefusesAModelTheAgentMayNotCall(t *testing.T) {
	f := newLLMFixture(t, "x")
	for _, tc := range []struct {
		model string
		want  string
	}{
		{"gpt-5", "model 'gpt-5' is not one this agent may call; it may call 'flash' (gemini-3.8-flash, chat), " +
			"'argon' (gemini-4-argon, chat), 's1' (system-one, decision)"},
		{"s1", "model 's1' is a decision model; ask it with llm_decide"},
	} {
		out := f.call(t, llmTokens(1000), llmInvocation("call", map[string]any{"model": tc.model, "prompt": "hi"}))
		if out.Success || out.Error != tc.want {
			t.Errorf("%s: %+v", tc.model, out)
		}
	}
	out := f.call(t, llmTokens(1000), llmInvocation("call", map[string]any{"model": "flash", "prompt": "hi"}, api.ToolModel{ModelID: llmArgon}))
	if out.Success || !strings.HasPrefix(out.Error, "model 'flash' is not one this agent may call") {
		t.Fatalf("out = %+v", out)
	}
	if len(f.models.calls) != 0 {
		t.Fatalf("a refused model was called: %+v", f.models.calls)
	}
}

func TestLLMCallReasoningAndBudgets(t *testing.T) {
	high, low, budget, out1 := "high", "low", 2048, 500
	entry := []api.ToolModel{{ModelID: llmFlash, ReasoningEffort: high, MaxTokens: &out1}, {ModelID: llmArgon, ReasoningMaxTokens: &budget}}
	for _, tc := range []struct {
		name        string
		args        map[string]any
		policy      int
		effort      string
		budget      *int
		maxTokens   int
		wantProblem string
	}{
		{name: "entry defaults", args: map[string]any{"model": "flash"}, policy: 1000, effort: high, maxTokens: 500},
		{name: "call effort", args: map[string]any{"model": "flash", "reasoning_effort": low, "max_tokens": float64(800)}, policy: 1000, effort: low, maxTokens: 800},
		{name: "policy caps", args: map[string]any{"model": "flash", "max_tokens": float64(5000)}, policy: 1000, effort: high, maxTokens: 1000},
		{name: "call budget replaces entry effort", args: map[string]any{"model": "flash", "reasoning_max_tokens": float64(300)}, policy: 1000,
			budget: &[]int{300}[0], maxTokens: 500},
		{name: "call effort replaces entry budget", args: map[string]any{"model": "argon", "reasoning_effort": low}, policy: 1000,
			wantProblem: "model gemini-4-argon takes no reasoning_effort"},
		{name: "entry budget", args: map[string]any{"model": "argon"}, policy: 1000, budget: &budget, maxTokens: 1000},
		{name: "both", args: map[string]any{"model": "flash", "reasoning_effort": low, "reasoning_max_tokens": float64(10)}, policy: 1000,
			wantProblem: "set reasoning_effort or reasoning_max_tokens, not both"},
		{name: "unknown level", args: map[string]any{"model": "flash", "reasoning_effort": "max"}, policy: 1000,
			wantProblem: "model gemini-3.8-flash takes reasoning_effort low, high, not max"},
		{name: "bad max_tokens", args: map[string]any{"model": "flash", "max_tokens": float64(0)}, policy: 1000,
			wantProblem: "max_tokens must be a positive integer"},
		{name: "fractional budget", args: map[string]any{"model": "flash", "reasoning_max_tokens": 1.5}, policy: 1000,
			wantProblem: "reasoning_max_tokens must be a positive integer"},
	} {
		f := newLLMFixture(t, "x")
		tc.args["prompt"] = "hi"
		out := f.call(t, llmTokens(tc.policy), llmInvocation("call", tc.args, entry...))
		if tc.wantProblem != "" {
			if out.Success || out.Error != tc.wantProblem || len(f.models.calls) != 0 {
				t.Errorf("%s: %+v", tc.name, out)
			}
			continue
		}
		if !out.Success || len(f.models.calls) != 1 {
			t.Errorf("%s: %+v", tc.name, out)
			continue
		}
		c := f.models.calls[0]
		gotBudget := 0
		if c.ReasoningMaxTokens != nil {
			gotBudget = *c.ReasoningMaxTokens
		}
		wantBudget := 0
		if tc.budget != nil {
			wantBudget = *tc.budget
		}
		if c.ReasoningEffort != tc.effort || gotBudget != wantBudget || c.MaxTokens != tc.maxTokens {
			t.Errorf("%s: effort %q budget %d max %d", tc.name, c.ReasoningEffort, gotBudget, c.MaxTokens)
		}
	}
}

func TestLLMCallHoldsForTheOutputAndReasoningBudget(t *testing.T) {
	f := newLLMFixture(t, "x")
	f.call(t, llmTokens(1000), llmInvocation("call", map[string]any{"model": "flash", "prompt": "hi", "max_tokens": float64(1000), "reasoning_max_tokens": float64(1000)}))
	small := newLLMFixture(t, "x")
	small.call(t, llmTokens(1000), llmInvocation("call", map[string]any{"model": "flash", "prompt": "hi", "max_tokens": float64(1000)}))
	if f.bill.authed[0].VendorCost.Cmp(small.bill.authed[0].VendorCost) <= 0 {
		t.Fatalf("the reasoning budget is not held: %s vs %s", f.bill.authed[0].VendorCost, small.bill.authed[0].VendorCost)
	}
}

func TestLLMCallAttachesImagesAndPDFs(t *testing.T) {
	f := newLLMFixture(t, "read")
	f.rt.files["sheets/a.png"] = pngBytes(t, 40, 30)
	f.rt.files["sheets/b.pdf"] = pdfOf(2)
	f.rt.files["notes.txt"] = []byte("text")
	f.rt.files["big.png"] = pngBytes(t, 2500, 10)
	f.rt.files["long.pdf"] = pdfOf(11)
	out := f.call(t, llmTokens(1000), llmInvocation("call", map[string]any{"model": "flash", "prompt": "read", "files": []any{"sheets/a.png", "sheets/b.pdf"}}))
	if !out.Success {
		t.Fatalf("out = %+v", out)
	}
	parts := f.models.calls[0].Messages[0].Parts
	if len(parts) != 3 || parts[0].Text != "read" || parts[1].Type != "image_url" || !strings.HasPrefix(parts[1].ImageURL, "data:image/png;base64,") ||
		parts[2].Type != "file" || !strings.HasPrefix(parts[2].FileData, "data:application/pdf;base64,") || parts[2].Filename != "b.pdf" {
		t.Fatalf("parts = %+v", parts)
	}
	for _, tc := range []struct {
		files []any
		model string
		want  string
	}{
		{[]any{"notes.txt"}, "flash", "notes.txt is neither an image (PNG, JPEG, GIF, WebP) nor a PDF"},
		{[]any{"missing.png"}, "flash", "file missing.png does not exist"},
		{[]any{"../x.png"}, "flash", "path escapes workspace sandbox: '../x.png'"},
		{[]any{"long.pdf"}, "flash", "long.pdf has 11 pages; a PDF attached here has at most 10: cut the pages you need into a new PDF in the shell"},
		{[]any{"big.png"}, "flash", "big.png: 2500x10 px is over the 2000 px edge this model takes; make a smaller copy or crop the part you need in the shell, then read_file that"},
		{[]any{"sheets/a.png"}, "argon", "model gemini-4-argon does not read images or PDFs"},
		{[]any{"sheets/a.png", 5}, "flash", "files must be a list of task workspace paths"},
	} {
		g := newLLMFixture(t, "x")
		g.rt.files = f.rt.files
		out := g.call(t, llmTokens(1000), llmInvocation("call", map[string]any{"model": tc.model, "prompt": "read", "files": tc.files}))
		if out.Success || out.Error != tc.want || len(g.models.calls) != 0 {
			t.Errorf("%v: %+v", tc.files, out)
		}
	}
}

func TestLLMCallSendsTheSchemaToTheModel(t *testing.T) {
	schema := map[string]any{"type": "object", "required": []any{"sockets"}, "properties": map[string]any{"sockets": map[string]any{"type": "integer"}}}
	f := newLLMFixture(t, "```json\n{\"sockets\": 4}\n```")
	out := f.call(t, llmTokens(1000), llmInvocation("call", map[string]any{"model": "flash", "prompt": "count", "schema": schema}))
	if !out.Success || out.Result != `{"sockets": 4}` {
		t.Fatalf("out = %+v", out)
	}
	if got := f.models.calls[0].ResponseSchema; got == nil || got["required"] == nil {
		t.Fatalf("schema sent = %+v", got)
	}
	if m := f.models.calls[0].Messages[0]; m.Role != "user" {
		t.Fatalf("the schema went into the prompt: %+v", m)
	}
	g := newLLMFixture(t, "sockets: 4")
	out = g.call(t, llmTokens(1000), llmInvocation("call", map[string]any{"model": "flash", "prompt": "count", "schema": schema, "output": "out.json"}))
	if out.Success || !strings.HasPrefix(out.Error, "the model answered text that is not JSON") || out.ModelBilling == nil || len(g.rt.files) != 0 {
		t.Fatalf("not JSON: %+v", out)
	}
}

func TestLLMCallWritesTheAnswerToOutput(t *testing.T) {
	f := newLLMFixture(t, "long answer")
	out := f.call(t, llmTokens(1000), llmInvocation("call", map[string]any{"model": "flash", "prompt": "x", "output": "answers/a.md"}))
	if !out.Success || string(f.rt.files["answers/a.md"]) != "long answer" ||
		out.Result != `{"file_path": "answers/a.md", "size": 11}` || out.ModelBilling == nil {
		t.Fatalf("out = %+v", out)
	}
	for _, path := range []string{"../a.md", "a.pdf"} {
		g := newLLMFixture(t, "x")
		if out := g.call(t, llmTokens(1000), llmInvocation("call", map[string]any{"model": "flash", "prompt": "x", "output": path})); out.Success || len(g.models.calls) != 0 {
			t.Errorf("%s: %+v", path, out)
		}
	}
}

func TestLLMCallAnswersARefusalAsTheToolsError(t *testing.T) {
	f := newLLMFixture(t, "x")
	f.bill.hold = money.HoldDecision{Allowed: false, Code: "insufficient_balance", Reason: "the balance is too low"}
	out := f.call(t, llmTokens(1000), llmInvocation("call", map[string]any{"model": "flash", "prompt": "x"}))
	if out.Success || out.Error != "the balance is too low" || len(f.models.calls) != 0 {
		t.Fatalf("out = %+v", out)
	}
	g := newLLMFixture(t, "x")
	g.models.err = &modelsapi.ModelCallError{Msg: "the provider refused"}
	if out := g.call(t, llmTokens(1000), llmInvocation("call", map[string]any{"model": "flash", "prompt": "x"})); out.Success || out.Error != "the provider refused" ||
		len(g.bill.voided) != 1 {
		t.Fatalf("out = %+v, voided %v", out, g.bill.voided)
	}
}

func TestLLMDecideAsksTheDecisionModel(t *testing.T) {
	f := newLLMFixture(t, "x")
	args := map[string]any{"model": "system-one", "state": map[string]any{"sheet": 3}, "questions": map[string]any{"q": map[string]any{"type": "choice"}}}
	out := f.call(t, llmTokens(1000), llmInvocation("decide", args))
	var answers map[string]map[string]any
	if !out.Success || json.Unmarshal([]byte(out.Result), &answers) != nil || answers["q"]["choice"] != "yes" || out.ModelBilling == nil {
		t.Fatalf("out = %+v", out)
	}
	args["output"] = "decision.json"
	if out := f.call(t, llmTokens(1000), llmInvocation("decide", args)); !out.Success || !strings.HasPrefix(out.Result, `{"file_path": "decision.json", "size": `) ||
		!strings.Contains(string(f.rt.files["decision.json"]), `"choice":"yes"`) {
		t.Fatalf("out = %+v", out)
	}
	args["model"] = "flash"
	if out := f.call(t, llmTokens(1000), llmInvocation("decide", args)); out.Success || out.Error != "model 'flash' is a chat model; call it with llm_call" {
		t.Fatalf("out = %+v", out)
	}
}

func TestLLMDecideAppendsFilesToTheState(t *testing.T) {
	f := newLLMFixture(t, "x")
	f.rt.files["plan.pdf"] = pdfOf(23)
	f.rt.files["sheet.png"] = pngBytes(t, 40, 30)
	text := map[string]any{"type": "text", "text": "a flat"}
	args := map[string]any{"model": "s1", "state": []any{text}, "files": []any{"plan.pdf", "sheet.png"},
		"questions": map[string]any{"q": map[string]any{"type": "choice"}}}
	if out := f.call(t, llmTokens(1000), llmInvocation("decide", args)); !out.Success {
		t.Fatalf("out = %+v", out)
	}
	items, _ := f.decided.State.([]any)
	if len(items) != 3 || items[0].(map[string]any)["text"] != "a flat" {
		t.Fatalf("state = %v", f.decided.State)
	}
	file := items[1].(map[string]any)["file"].(map[string]any)
	if file["filename"] != "plan.pdf" || !strings.HasPrefix(file["file_data"].(string), "data:application/pdf;base64,") {
		t.Fatalf("a 23-page PDF goes whole: %v", items[1])
	}
	if img := items[2].(map[string]any)["image_url"].(map[string]any); !strings.HasPrefix(img["url"].(string), "data:image/png;base64,") {
		t.Fatalf("image item = %v", items[2])
	}
	args["state"] = map[string]any{"sheet": 3}
	if out := f.call(t, llmTokens(1000), llmInvocation("decide", args)); out.Success || out.Error != "with files, state must be a list of state items" {
		t.Fatalf("object state with files: %+v", out)
	}
}

func TestLLMToolNeedsATask(t *testing.T) {
	f := newLLMFixture(t, "x")
	inv := llmInvocation("call", map[string]any{"model": "flash", "prompt": "x"})
	inv.TaskID = ""
	if out := f.call(t, llmTokens(1000), inv); out.Success || out.Error == "" {
		t.Fatalf("out = %+v", out)
	}
}

func TestLLMToolIsUnwiredWithoutItsModels(t *testing.T) {
	s := New(Deps{Log: quiet()})
	inv := llmInvocation("call", map[string]any{"model": "flash", "prompt": "x"})
	_, err := s.llmCaller(ToolCall{Binding: inv.Binding}).Call(context.Background(), inv)
	if err == nil || errors.Is(err, context.Canceled) {
		t.Fatalf("err = %v", err)
	}
}
