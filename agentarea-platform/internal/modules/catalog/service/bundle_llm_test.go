package service

import (
	"encoding/json"
	"errors"
	"reflect"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

const llmBundle = `
name: reader
setup:
  - {key: effort, label: Effort, type: string, default: high}
agents:
  - key: reader
    name: Reader
    model: us-model
    toolsets:
      - agentarea/files
      - name: agentarea/llm
        models:
          - gpt-5
          - name: s1
          - name: us
            reasoning_effort: "${setup.effort}"
            max_tokens: 4000
`

func i64(n int64) *int64 { return &n }
func intp(n int) *int    { return &n }

func llmToolsets() []BundleToolset {
	return []BundleToolset{{Name: "agentarea/files"}, {Name: "agentarea/llm", Models: []BundleToolsetModel{
		{Name: "gpt-5"}, {Name: "s1"}, {Name: "us", ReasoningEffort: strp("${setup.effort}"), MaxTokens: i64(4000)}}}}
}

func TestBundleLLMToolsetModelsAreNamesOrMappings(t *testing.T) {
	b := mustParse(t, llmBundle)
	if got := b.Agents[0].Toolsets; !reflect.DeepEqual(got, llmToolsets()) {
		t.Fatalf("toolsets = %+v", got)
	}
	dumped, _ := b.Agents[0].dump().Get("toolsets")
	want := []any{"agentarea/files", wirejson.Object{{Key: "name", Value: "agentarea/llm"}, {Key: "models", Value: []any{"gpt-5", "s1",
		wirejson.Object{{Key: "name", Value: "us"}, {Key: "reasoning_effort", Value: "${setup.effort}"}, {Key: "max_tokens", Value: json.Number("4000")}}}}}}
	if !reflect.DeepEqual(dumped, want) {
		t.Fatalf("dump = %#v", dumped)
	}
	var c checker
	again, ok := bundleAgentFrom(&c, b.Agents[0].dump(), nil)
	if !ok || !reflect.DeepEqual(again.Toolsets, llmToolsets()) {
		t.Fatalf("reparsed = %+v, %v", again.Toolsets, c.errs)
	}
}

func TestBundleLLMToolsetModelErrors(t *testing.T) {
	model := func(m ...wirejson.Member) wirejson.Object { return wirejson.Object(m) }
	for _, tc := range []struct {
		models any
		typ    string
		loc    []any
	}{
		{"gpt-5", "list_type", []any{"toolsets", 0, "models"}},
		{[]any{model(wirejson.Member{Key: "reasoning_effort", Value: "high"})}, "missing", []any{"toolsets", 0, "models", 0, "name"}},
		{[]any{model(wirejson.Member{Key: "name", Value: "x"}, wirejson.Member{Key: "effort", Value: "high"})}, "extra_forbidden",
			[]any{"toolsets", 0, "models", 0, "effort"}},
		{[]any{model(wirejson.Member{Key: "name", Value: "x"}, wirejson.Member{Key: "max_tokens", Value: json.Number("0")})}, "value_error",
			[]any{"toolsets", 0, "models", 0, "max_tokens"}},
		{[]any{model(wirejson.Member{Key: "name", Value: "x"}, wirejson.Member{Key: "reasoning_effort", Value: "high"},
			wirejson.Member{Key: "reasoning_max_tokens", Value: json.Number("100")})}, "value_error", []any{"toolsets", 0, "models", 0}},
		{[]any{5}, "value_error", []any{"toolsets", 0, "models", 0}},
	} {
		var c checker
		ts := wirejson.Object{{Key: "name", Value: "agentarea/llm"}, {Key: "models", Value: tc.models}}
		_, ok := bundleAgentFrom(&c, wirejson.Object{{Key: "key", Value: "a"}, {Key: "name", Value: "A"}, {Key: "toolsets", Value: []any{ts}}}, nil)
		if ok || len(c.errs) != 1 || c.errs[0].Type != tc.typ || !reflect.DeepEqual(c.errs[0].Loc, tc.loc) {
			t.Errorf("%v: ok=%v errors = %+v", tc.models, ok, c.errs)
		}
	}
}

func TestBundleFolderAgentTakesLLMModels(t *testing.T) {
	b, _, err := LoadBundleFolder(StrPairs{{"agent.yaml", "name: r\nmodel: m\ntoolsets:\n  - name: agentarea/llm\n" +
		"    models: [gemini-flash, {name: argon, reasoning_max_tokens: 2048}]\n"}, {"instructions.md", "Go.\n"}})
	want := []BundleToolset{{Name: "agentarea/llm", Models: []BundleToolsetModel{{Name: "gemini-flash"}, {Name: "argon", ReasoningMaxTokens: i64(2048)}}}}
	if err != nil || !reflect.DeepEqual(b.Agents[0].Toolsets, want) {
		t.Fatalf("toolsets = %+v, %v", b.Agents[0].Toolsets, err)
	}
}

func llmTools() []catalogapi.BundleTool {
	return []catalogapi.BundleTool{{Type: "code", Name: "agentarea/files"}, {Type: "code", Name: "agentarea/llm", Models: []catalogapi.BundleToolModel{
		{ModelID: "model-gpt"}, {ModelID: "model-s1"}, {ModelID: "model-us", ReasoningEffort: strp("high"), MaxTokens: intp(4000)}}}}
}

func TestBundleAnalyzeResolvesLLMModels(t *testing.T) {
	f := newDeployFixture(t)
	p := analyzeWith(t, f, llmBundle, nil)
	if len(p.Blocks()) != 0 || len(f.agents.checked) != 1 {
		t.Fatalf("blocks = %v, checked %+v", blockMessages(p), f.agents.checked)
	}
	if got := f.agents.checked[0].Toolsets; !reflect.DeepEqual(got, llmTools()) {
		t.Fatalf("checked toolsets = %+v", got)
	}

	f = newDeployFixture(t)
	p = analyzeWith(t, f, strings.Replace(llmBundle, "- name: s1", "- name: veo", 1), nil)
	want := []string{"agent 'reader': toolset 'agentarea/llm': models 'veo' names no active chat or decision model instance in this workspace; " +
		"the workspace has 'us-model' (us), 'GPT' (gpt-5), 's1' (system-one)"}
	if got := blockMessages(p); !reflect.DeepEqual(got, want) || len(f.agents.checked) != 0 {
		t.Fatalf("blocks = %q", got)
	}
}

func TestBundleInstallAndRedeployFollowLLMModels(t *testing.T) {
	f := newDeployFixture(t)
	first := mustParse(t, llmBundle)
	_, res, err := f.install(t, &first, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(f.agents.created) != 1 || !reflect.DeepEqual(f.agents.created[0].Tools, llmTools()) {
		t.Fatalf("created = %+v", f.agents.created)
	}
	prior := &priorInstall{bundle: first, result: res}
	if _, _, err := f.install(t, &first, prior); err != nil || len(f.agents.updates) != 0 {
		t.Fatalf("unchanged redeploy: updates %+v, %v", f.agents.updates, err)
	}
	changed := mustParse(t, strings.Replace(llmBundle, "max_tokens: 4000", "max_tokens: 8000", 1))
	if _, _, err := f.install(t, &changed, prior); err == nil {
		t.Fatal("a settings change was applied without the plan's approval")
	}
	if _, _, err := f.install(t, &changed, prior, entityRef{KindAgent, "reader"}); err != nil || len(f.agents.updates) != 1 {
		t.Fatalf("updates %+v, %v", f.agents.updates, err)
	}
	if got := f.agents.updates[0].Tools[1].Models[2].MaxTokens; got == nil || *got != 8000 {
		t.Fatalf("update = %+v", f.agents.updates[0].Tools[1])
	}

	f = newDeployFixture(t)
	bad := mustParse(t, strings.Replace(llmBundle, "- gpt-5", "- nope", 1))
	_, _, err = f.install(t, &bad, nil)
	var be *BundleError
	if !errors.As(err, &be) || !strings.HasPrefix(be.Msg, "agent 'reader': toolset 'agentarea/llm': models 'nope' names no active chat or decision model instance") {
		t.Fatalf("err = %v", err)
	}
}
