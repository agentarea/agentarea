package mcpserver

import (
	"context"
	"errors"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
)

type fakeProviders struct{ *recorder }

func (f fakeProviders) ListSpecs(_ context.Context, c authn.Caller) ([]modelsapi.ProviderSpecSummary, error) {
	f.saw("specs %s", c.Workspace.ID())
	return []modelsapi.ProviderSpecSummary{{ID: "p1", Name: "OpenAI", Key: "openai"}}, nil
}
func (f fakeProviders) ListConfigs(context.Context, authn.Caller) ([]modelsapi.ProviderConfigSummary, error) {
	f.saw("configs")
	return []modelsapi.ProviderConfigSummary{{ID: "c1", Name: "Main", ProviderSpecID: "p1", IsActive: true}}, nil
}
func (f fakeProviders) CreateConfig(_ context.Context, _ authn.Caller, n modelsapi.NewProviderConfig) (modelsapi.ProviderConfigRef, error) {
	f.saw("create %+v", n)
	if n.Name == "refused" {
		return modelsapi.ProviderConfigRef{}, errors.New("Only a workspace admin may perform this action")
	}
	return modelsapi.ProviderConfigRef{ID: "c2", Name: n.Name}, nil
}
func (f fakeProviders) UpdateConfig(_ context.Context, _ authn.Caller, id string, p modelsapi.ProviderConfigPatch) (modelsapi.ProviderConfigRef, error) {
	f.saw("update %s name=%v key=%v active=%v", id, p.Name != nil, p.APIKey != nil, p.IsActive != nil)
	if id == "gone" {
		return modelsapi.ProviderConfigRef{}, modelsapi.ErrNotFound
	}
	return modelsapi.ProviderConfigRef{ID: id, Name: "Renamed"}, nil
}
func (f fakeProviders) DeleteConfig(_ context.Context, _ authn.Caller, id string) (bool, error) {
	f.saw("delete %s", id)
	return id != "gone", nil
}

type fakeModels struct{ *recorder }

func (f fakeModels) ListSpecs(context.Context, authn.Caller) ([]modelsapi.ModelSpecSummary, error) {
	f.saw("specs")
	return []modelsapi.ModelSpecSummary{{ID: "s1", Name: "GPT", ProviderSpecID: "p1"}}, nil
}
func (f fakeModels) ListInstances(context.Context, authn.Caller) ([]modelsapi.ModelInstanceSummary, error) {
	f.saw("instances")
	return []modelsapi.ModelInstanceSummary{{ID: "m1", Name: "gpt", ModelSpecID: "s1", ProviderConfigID: "c1", IsActive: true}}, nil
}
func (f fakeModels) CreateInstance(_ context.Context, _ authn.Caller, n modelsapi.NewModelInstance) (modelsapi.ModelInstanceSummary, error) {
	f.saw("create %+v", n)
	return modelsapi.ModelInstanceSummary{ID: "m2", Name: n.Name, ModelSpecID: n.ModelSpecID, ProviderConfigID: n.ProviderConfigID, IsActive: true}, nil
}
func (f fakeModels) GetInstance(_ context.Context, _ authn.Caller, id string) (modelsapi.ModelInstanceSummary, error) {
	f.saw("get %s", id)
	if id == "gone" {
		return modelsapi.ModelInstanceSummary{}, modelsapi.ErrNotFound
	}
	return modelsapi.ModelInstanceSummary{ID: id, Name: "gpt"}, nil
}

func TestProvidersToolset(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{LLMProviders: fakeProviders{rec}}, "providers")
	runToolCases(t, ts, rec, []toolCase{
		{"providers_list_specs", `{}`, "specs " + wsID, `[{"id":"p1","key":"openai","name":"OpenAI"}]`, false},
		{"providers_list_configs", `{}`, "configs", `[{"id":"c1","is_active":true,"name":"Main","provider_spec_id":"p1"}]`, false},
		{"providers_create_config", `{"provider_spec_id":"p1","name":"Main","api_key":"sk"}`,
			"create {ProviderSpecID:p1 Name:Main APIKey:sk EndpointURL: Description: IsPublic:false}", `{"id":"c2","name":"Main"}`, false},
		{"providers_create_config", `{"provider_spec_id":"p1","name":"refused","api_key":""}`, "", "Only a workspace admin may perform this action", true},
		{"providers_update_config", `{"config_id":"c1","name":"Renamed","api_key":null,"is_active":false}`,
			"update c1 name=true key=false active=true", `{"id":"c1","name":"Renamed"}`, false},
		{"providers_update_config", `{"config_id":"gone"}`, "", "Provider configuration not found", true},
		{"providers_delete_config", `{"config_id":"c1"}`, "delete c1", `{"deleted":true}`, false},
		{"providers_delete_config", `{"config_id":"gone"}`, "delete gone", `{"deleted":false}`, false},
	})
}

func TestModelsToolset(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{Models: fakeModels{rec}}, "models")
	runToolCases(t, ts, rec, []toolCase{
		{"models_list_specs", `{}`, "specs", `[{"id":"s1","name":"GPT","provider_spec_id":"p1"}]`, false},
		{"models_list_instances", `{}`, "instances", `"provider_config_id":"c1"`, false},
		{"models_create_instance", `{"provider_config_id":"c1","model_spec_id":"s1","name":"gpt"}`,
			"create {ProviderConfigID:c1 ModelSpecID:s1 Name:gpt Description:}", `"id":"m2"`, false},
		{"models_get", `{"model_instance_id":"m1"}`, "get m1", `"id":"m1"`, false},
		{"models_get", `{"model_instance_id":"gone"}`, "get gone", "Model instance not found", true},
	})
}
