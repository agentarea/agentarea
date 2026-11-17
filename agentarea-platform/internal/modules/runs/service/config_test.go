package service

import (
	"context"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

type configAgents map[string]agentsapi.Definition

func (f configAgents) Definition(_ context.Context, _ scope.Workspace, id string) (agentsapi.Definition, error) {
	d, ok := f[id]
	if !ok {
		return agentsapi.Definition{}, agentsapi.ErrNotFound
	}
	return d, nil
}

type configModels struct{ strategy string }

func (f configModels) Model(_ context.Context, _ modelsapi.Principal, id string) (modelsapi.ResolvedModel, error) {
	return modelsapi.ResolvedModel{ModelID: id, ContextWindow: 200000, DefaultContextStrategy: f.strategy}, nil
}

type configRuntime struct{ sandboxapi.Runtime }

func (configRuntime) Manifest(context.Context) (*sandboxapi.RuntimeManifest, error) { return nil, nil }

type configDefinitions struct{ tools ToolSet }

func (f configDefinitions) Tools(context.Context, Principal, ToolsRequest) (ToolSet, error) {
	return f.tools, nil
}

func (configDefinitions) Skills(context.Context, Principal, api.AgentSpec, []string) ([]api.Skill, []api.WithheldSkill, error) {
	return nil, nil, nil
}

func (configDefinitions) ProjectInstructions(context.Context, Principal, string) ([]string, error) {
	return nil, nil
}

func (configDefinitions) Inputs(context.Context, Principal, InputsRequest) ([]api.InputFile, error) {
	return nil, nil
}

const researcherID = "7d2e4c1a-5b3f-4e8d-9a6c-2f1b0e9d8c7a"

func delegatingRun(t *testing.T, strategy string, delegate agentsapi.Definition, settings agentsapi.ToolSettings) api.RunConfig {
	t.Helper()
	p := testPrincipal()
	agents := configAgents{
		p.AgentID: {ID: p.AgentID, Name: "Coordinator", ModelID: "model-1", Tools: []agentsapi.Tool{
			{Type: "code", Name: "agentarea/files"},
			{Type: "agent", Name: "Eval Research", Settings: settings},
		}},
		researcherID: delegate,
	}
	files := api.ToolDefinition{Name: "files_read", Parameters: map[string]any{"type": "object"}}
	svc := New(Deps{
		Agents: agents, Resolver: configModels{strategy: strategy}, Runtime: configRuntime{},
		Definitions: configDefinitions{tools: ToolSet{
			Tools:         []api.ToolDefinition{files},
			ToolProviders: []api.ToolProvider{{Name: "agentarea/files", ProviderType: "code", Tools: []api.ToolDefinition{files}}},
			Bindings:      map[string]api.ToolBinding{"files_read": {Source: "code"}},
		}},
		Settings: RunSettings{OutageWait: api.OutageWait{RetryWindow: time.Minute}, SkillsWindowShare: 0.3},
		Log:      quiet(), Now: fixedNow,
	})
	cfg, err := svc.ResolveRunConfig(context.Background(), p, ResolveInput{})
	if err != nil {
		t.Fatalf("ResolveRunConfig: %v", err)
	}
	return cfg
}

func toolNamed(tools []api.ToolDefinition, name string) (api.ToolDefinition, bool) {
	for _, t := range tools {
		if t.Name == name {
			return t, true
		}
	}
	return api.ToolDefinition{}, false
}

func TestResolveRunConfigOffersTheModelALocalDelegate(t *testing.T) {
	cfg := delegatingRun(t, "static",
		agentsapi.Definition{ID: researcherID, Name: "Eval Research", Description: "Researches evaluation results."},
		agentsapi.ToolSettings{AgentID: researcherID})

	const tool = "delegate_to_Eval_Research"
	if got := cfg.Delegates[tool]; got.AgentID != researcherID || got.AgentName != "Eval Research" {
		t.Fatalf("delegate = %+v, want agent %s named Eval Research", got, researcherID)
	}
	def, ok := toolNamed(cfg.Tools, tool)
	if !ok {
		t.Fatalf("the model is not offered %s; tools: %+v", tool, cfg.Tools)
	}
	if want := "Delegate a task to the 'Eval Research' agent. Researches evaluation results."; def.Description != want {
		t.Errorf("description = %q, want %q", def.Description, want)
	}
	props, _ := def.Parameters["properties"].(map[string]any)
	if _, ok := props["message"]; !ok {
		t.Errorf("parameters = %+v, want a message property", def.Parameters)
	}
	if req, _ := def.Parameters["required"].([]any); len(req) != 1 || req[0] != "message" {
		t.Errorf("required = %v, want [message]", def.Parameters["required"])
	}
	if _, ok := toolNamed(cfg.Tools, "files_read"); !ok {
		t.Errorf("the connection tools were dropped: %+v", cfg.Tools)
	}
}

func TestResolveRunConfigOffersADelegateAsAToolSourceInDynamicMode(t *testing.T) {
	cfg := delegatingRun(t, "dynamic",
		agentsapi.Definition{ID: researcherID, Name: "Eval Research"},
		agentsapi.ToolSettings{AgentID: researcherID, DescriptionOverride: "Owns the eval write-ups."})

	for _, p := range cfg.ToolProviders {
		if p.Name != "Eval Research" {
			continue
		}
		if p.ProviderType != "agent" || p.Description != "Agent: Eval Research" {
			t.Errorf("provider = %+v, want an agent source", p)
		}
		def, ok := toolNamed(p.Tools, "delegate_to_Eval_Research")
		if !ok {
			t.Fatalf("the source has no delegation tool: %+v", p.Tools)
		}
		if want := "Delegate a task to the 'Eval Research' agent. Owns the eval write-ups."; def.Description != want {
			t.Errorf("description = %q, want %q", def.Description, want)
		}
		return
	}
	t.Fatalf("no tool source for the delegate: %+v", cfg.ToolProviders)
}

func TestResolveRunConfigDoesNotOfferAnArchivedDelegate(t *testing.T) {
	cfg := delegatingRun(t, "static",
		agentsapi.Definition{ID: researcherID, Name: "Eval Research", Archived: true},
		agentsapi.ToolSettings{AgentID: researcherID})

	if _, ok := cfg.Delegates["delegate_to_Eval_Research"]; ok {
		t.Errorf("an archived agent is a delegate: %+v", cfg.Delegates)
	}
	if _, ok := toolNamed(cfg.Tools, "delegate_to_Eval_Research"); ok {
		t.Errorf("an archived agent is offered to the model: %+v", cfg.Tools)
	}
}
