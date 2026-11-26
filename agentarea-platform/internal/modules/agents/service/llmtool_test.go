package service

import (
	"context"
	"reflect"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
)

type llmFakeModels map[string]modelsapi.InstanceName

func (m llmFakeModels) ModelKind(_ context.Context, _ scope.Workspace, id string) (string, bool, error) {
	n, ok := m[id]
	return n.Kind, ok, nil
}

func (m llmFakeModels) InstanceName(_ context.Context, _ scope.Workspace, id string) (modelsapi.InstanceName, bool, error) {
	n, ok := m[id]
	return n, ok, nil
}

func TestToolModelsRoundTrip(t *testing.T) {
	tool, errs := parse(t, `{"type":"code","name":"agentarea/llm","settings":{"models":[{"model_id":"m1"},`+
		`{"model_id":"m2","reasoning_effort":"high","max_tokens":4000},{"model_id":"m3","reasoning_max_tokens":2048}]}}`)
	if len(errs) != 0 {
		t.Fatal(errs)
	}
	stored, _ := wirejson.Marshal(ToolStored(tool), wirejson.Compact)
	want := `{"name":"agentarea/llm","type":"code","settings":{"models":[{"model_id":"m1"},` +
		`{"model_id":"m2","reasoning_effort":"high","max_tokens":4000},{"model_id":"m3","reasoning_max_tokens":2048}]}}`
	if string(stored) != want {
		t.Errorf("stored %s", stored)
	}
	resp, _ := wirejson.Marshal(ToolResponse(tool), wirejson.Compact)
	wantResp := `{"name":"agentarea/llm","type":"code","settings":{"requires_user_confirmation":null,"disabled_methods":null,` +
		`"image_model_id":null,"video_model_id":null,"models":[` +
		`{"model_id":"m1","reasoning_effort":null,"reasoning_max_tokens":null,"max_tokens":null},` +
		`{"model_id":"m2","reasoning_effort":"high","reasoning_max_tokens":null,"max_tokens":4000},` +
		`{"model_id":"m3","reasoning_effort":null,"reasoning_max_tokens":2048,"max_tokens":null}]}}`
	if string(resp) != wantResp {
		t.Errorf("response %s", resp)
	}
	effort, budget, out := "high", 2048, 4000
	got := apiTool(tool).Settings.Models
	if !reflect.DeepEqual(got, []api.ToolModel{{ModelID: "m1"}, {ModelID: "m2", ReasoningEffort: effort, MaxTokens: &out},
		{ModelID: "m3", ReasoningMaxTokens: &budget}}) {
		t.Errorf("definition %+v", got)
	}
}

func TestToolModelsParseErrors(t *testing.T) {
	for raw, typ := range map[string]string{
		`{"models":"m1"}`:             "list_type",
		`{"models":["m1"]}`:           "model_attributes_type",
		`{"models":[{}]}`:             "missing",
		`{"models":[{"model_id":5}]}`: "string_type",
		`{"models":[{"model_id":"m","reasoning_effort":1}]}`:       "string_type",
		`{"models":[{"model_id":"m","max_tokens":0}]}`:             "value_error",
		`{"models":[{"model_id":"m","reasoning_max_tokens":1.5}]}`: "value_error",
		`{"models":[{"model_id":"m","max_tokens":"x"}]}`:           "value_error",
	} {
		_, errs := parse(t, `{"type":"code","name":"agentarea/llm","settings":`+raw+`}`)
		if len(errs) != 1 || errs[0].Type != typ {
			t.Errorf("%s: %v, want one %s", raw, errs, typ)
		}
	}
}

func TestAgentProblemChecksTheLLMToolsetModels(t *testing.T) {
	chat, decision, image, plain := uuid.NewString(), uuid.NewString(), uuid.NewString(), uuid.NewString()
	models := llmFakeModels{
		chat:     {ID: chat, Name: "flash", ModelName: "gemini-flash", Kind: "chat", ReasoningLevels: []string{"low", "high"}},
		decision: {ID: decision, Name: "s1", ModelName: "system-one", Kind: "decision"},
		image:    {ID: image, Name: "pic", ModelName: "flux", Kind: "image"},
		plain:    {ID: plain, Name: "plain", ModelName: "plain-1", Kind: "chat"},
	}
	b := BundleAgents{K: &Skills{s: New(Deps{Models: models, CodeTools: bundleFakeCodeTools{"agentarea/llm", "agentarea/media", "agentarea/files"}})}}
	high, nope, budget, zero, out := "high", "max", 2048, 0, 1000
	missing := uuid.NewString()
	entry := func(id string) catalogapi.BundleToolModel { return catalogapi.BundleToolModel{ModelID: id} }
	llm := func(m ...catalogapi.BundleToolModel) catalogapi.BundleTool {
		return catalogapi.BundleTool{Type: "code", Name: "agentarea/llm", Models: m}
	}
	for _, tc := range []struct {
		tool catalogapi.BundleTool
		want string
	}{
		{llm(entry(chat), entry(decision)), ""},
		{llm(catalogapi.BundleToolModel{ModelID: chat, ReasoningEffort: &high, MaxTokens: &out}), ""},
		{llm(catalogapi.BundleToolModel{ModelID: chat, ReasoningMaxTokens: &budget}), ""},
		{llm(), "Tool 'agentarea/llm' needs at least one model in models."},
		{llm(entry(image)), "Model instance '" + image + "' is a image model; models of 'agentarea/llm' must be chat or decision models."},
		{llm(entry(missing)), "Model instance '" + missing + "' does not exist in this workspace. Create one via POST /v1/model-instances."},
		{llm(entry("nope")), "Invalid models 'nope': expected the UUID of a model instance. List available instances via GET /v1/model-instances."},
		{llm(entry(chat), entry(chat)), "Model instance '" + chat + "' is listed twice in models of 'agentarea/llm'."},
		{llm(catalogapi.BundleToolModel{ModelID: chat, ReasoningEffort: &high, ReasoningMaxTokens: &budget}),
			"Model instance '" + chat + "' in models of 'agentarea/llm': set reasoning_effort or reasoning_max_tokens, not both"},
		{llm(catalogapi.BundleToolModel{ModelID: chat, ReasoningEffort: &nope}),
			"Model instance '" + chat + "' in models of 'agentarea/llm': model gemini-flash takes reasoning_effort low, high, not max"},
		{llm(catalogapi.BundleToolModel{ModelID: plain, ReasoningEffort: &high}),
			"Model instance '" + plain + "' in models of 'agentarea/llm': model plain-1 takes no reasoning_effort"},
		{llm(catalogapi.BundleToolModel{ModelID: decision, MaxTokens: &out}),
			"Model instance '" + decision + "' in models of 'agentarea/llm': a decision model takes no reasoning_effort, reasoning_max_tokens or max_tokens"},
		{llm(catalogapi.BundleToolModel{ModelID: chat, MaxTokens: &zero}),
			"Model instance '" + chat + "' in models of 'agentarea/llm': max_tokens must be a positive integer"},
		{catalogapi.BundleTool{Type: "code", Name: "agentarea/media", ImageModelID: &image, Models: []catalogapi.BundleToolModel{entry(chat)}},
			"Tool 'agentarea/media' takes no models."},
		{catalogapi.BundleTool{Type: "code", Name: "agentarea/llm", ImageModelID: &image, Models: []catalogapi.BundleToolModel{entry(chat)}},
			"Tool 'agentarea/llm' takes no image_model_id."},
	} {
		got, err := b.AgentProblem(context.Background(), authn.Caller{}, catalogapi.BundleAgentConfig{Toolsets: []catalogapi.BundleTool{tc.tool}})
		if err != nil || got != tc.want {
			t.Errorf("%+v: problem = %q, %v; want %q", tc.tool, got, err, tc.want)
		}
	}
}

// A redeploy gives the toolset the folder's models; its other settings stay.
func TestBundleToolsAfterTakesTheFolderModelsOfTheLLMToolset(t *testing.T) {
	high := "high"
	confirm := true
	current := []domain.Tool{{Type: domain.ToolCode, Name: "agentarea/llm", Settings: &domain.Settings{
		Models: &[]domain.ToolModel{{ModelID: "old"}}, RequiresUserConfirmation: &confirm}}}
	declared := []catalogapi.BundleTool{{Type: "code", Name: "agentarea/llm",
		Models: []catalogapi.BundleToolModel{{ModelID: "new", ReasoningEffort: &high}, {ModelID: "s1"}}}}
	got := bundleToolsAfter(current, catalogapi.BundleAgentUpdate{Tools: declared, ManagedTools: declared})
	want := []domain.Tool{{Type: domain.ToolCode, Name: "agentarea/llm", Settings: &domain.Settings{
		Models: &[]domain.ToolModel{{ModelID: "new", ReasoningEffort: &high}, {ModelID: "s1"}}, RequiresUserConfirmation: &confirm}}}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("tools = %+v", got[0].Settings)
	}
	if (*current[0].Settings.Models)[0].ModelID != "old" {
		t.Fatal("the current tool's settings were written through")
	}
	added := bundleTool(declared[0])
	if added.Settings == nil || !reflect.DeepEqual(*added.Settings.Models, (*want[0].Settings.Models)) {
		t.Fatalf("added = %+v", added)
	}
	if plain := bundleTool(catalogapi.BundleTool{Type: "code", Name: "agentarea/files"}); plain.Settings != nil {
		t.Fatalf("a toolset without settings got %+v", plain.Settings)
	}
}
