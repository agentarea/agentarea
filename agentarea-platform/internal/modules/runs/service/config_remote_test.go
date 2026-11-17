package service

import (
	"slices"
	"testing"

	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

func TestResolveRunConfigOffersTheModelARemoteDelegate(t *testing.T) {
	cfg := delegatingRun(t, "static", agentsapi.Definition{},
		agentsapi.ToolSettings{A2AURL: "https://remote.test/a2a", AuthSecretName: "remote-key"})

	const tool = "delegate_to_Eval_Research"
	if _, local := cfg.Delegates[tool]; local {
		t.Fatalf("a remote delegate is run as a local one: %+v", cfg.Delegates)
	}
	def, ok := toolNamed(cfg.Tools, tool)
	if !ok {
		t.Fatalf("the model is not offered %s; tools: %+v", tool, cfg.Tools)
	}
	if want := "Delegate a task to the 'Eval Research' agent. Remote agent: Eval Research"; def.Description != want {
		t.Errorf("description = %q, want %q", def.Description, want)
	}
	if req, _ := def.Parameters["required"].([]any); len(req) != 1 || req[0] != "message" {
		t.Errorf("required = %v, want [message]", def.Parameters["required"])
	}
	b := cfg.Bindings[tool]
	if b.Source != "remote_agent" || b.RemoteAgent == nil ||
		*b.RemoteAgent != (api.RemoteAgentBinding{AgentName: "Eval Research", A2AURL: "https://remote.test/a2a", AuthSecretName: "remote-key"}) {
		t.Fatalf("binding = %+v", b)
	}
	if !slices.Equal(b.PolicyNames, []string{"a2a:https://remote.test/a2a"}) {
		t.Errorf("policy names = %v", b.PolicyNames)
	}
	var provider *api.ToolProvider
	for i := range cfg.ToolProviders {
		if cfg.ToolProviders[i].Name == "Eval Research" {
			provider = &cfg.ToolProviders[i]
		}
	}
	if provider == nil || provider.ProviderType != "agent" || len(provider.Tools) != 1 || provider.Tools[0].Name != tool {
		t.Fatalf("tool source = %+v", provider)
	}
}

func TestResolveRunConfigUsesADescriptionOverrideForARemoteDelegate(t *testing.T) {
	cfg := delegatingRun(t, "static", agentsapi.Definition{},
		agentsapi.ToolSettings{A2AURL: "https://remote.test/a2a", DescriptionOverride: "Writes the docs."})

	def, ok := toolNamed(cfg.Tools, "delegate_to_Eval_Research")
	if !ok || def.Description != "Delegate a task to the 'Eval Research' agent. Writes the docs." {
		t.Fatalf("tool = %+v %v", def, ok)
	}
	if b := cfg.Bindings["delegate_to_Eval_Research"]; b.RemoteAgent == nil || b.RemoteAgent.AuthSecretName != "" {
		t.Fatalf("binding = %+v", b)
	}
}
