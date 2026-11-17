package service

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	modelsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	sandboxapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
)

type noTenantAgents struct{}

func (noTenantAgents) Definition(context.Context, scope.Workspace, string) (agentsapi.Definition, error) {
	return agentsapi.Definition{}, agentsapi.ErrNotFound
}

type catalogRunAgents struct {
	defs  map[string]agentsapi.Definition
	refus string
	users []string
}

func (f *catalogRunAgents) CatalogDefinition(_ context.Context, _ scope.Workspace, userID, id string) (agentsapi.Definition, error) {
	f.users = append(f.users, userID)
	if f.refus != "" {
		return agentsapi.Definition{}, &agentsapi.AgentRefusedError{Msg: f.refus}
	}
	d, ok := f.defs[id]
	if !ok {
		return agentsapi.Definition{}, agentsapi.ErrNotFound
	}
	return d, nil
}

type catalogRunModels struct{}

func (catalogRunModels) Model(_ context.Context, _ modelsapi.Principal, id string) (modelsapi.ResolvedModel, error) {
	return modelsapi.ResolvedModel{ModelID: id, ContextWindow: 200000, DefaultContextStrategy: "static"}, nil
}

type catalogRunRuntime struct{ sandboxapi.Runtime }

func (catalogRunRuntime) Manifest(context.Context) (*sandboxapi.RuntimeManifest, error) {
	return nil, nil
}

type catalogRunDefinitions struct{ RunDefinitions }

func (catalogRunDefinitions) Tools(context.Context, Principal, ToolsRequest) (ToolSet, error) {
	return ToolSet{}, nil
}

func (catalogRunDefinitions) Skills(context.Context, Principal, api.AgentSpec, []string) ([]api.Skill, []api.WithheldSkill, error) {
	return nil, nil, nil
}

func (catalogRunDefinitions) ProjectInstructions(context.Context, Principal, string) ([]string, error) {
	return nil, nil
}

func (catalogRunDefinitions) Inputs(context.Context, Principal, InputsRequest) ([]api.InputFile, error) {
	return nil, nil
}

func catalogRunService(cat *catalogRunAgents) *Service {
	return New(Deps{
		Agents: noTenantAgents{}, CatalogAgents: cat, Resolver: catalogRunModels{}, Runtime: catalogRunRuntime{},
		Definitions: catalogRunDefinitions{},
		Settings:    RunSettings{OutageWait: api.OutageWait{RetryWindow: time.Minute}, SkillsWindowShare: 0.3},
		Log:         quiet(), Now: fixedNow,
	})
}

func TestResolveRunConfigRunsAnUninstalledCatalogAgentFromItsDefinition(t *testing.T) {
	p := testPrincipal()
	cat := &catalogRunAgents{defs: map[string]agentsapi.Definition{p.AgentID: {ID: p.AgentID, Name: "Researcher", Instruction: "Find things", AgentType: "stateless"}}}
	cfg, err := catalogRunService(cat).ResolveRunConfig(context.Background(), p, ResolveInput{ModelOverride: "model-1"})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Agent.Name != "Researcher" || cfg.Agent.Instruction != "Find things" || cfg.Agent.ModelID != "model-1" {
		t.Fatalf("agent %+v", cfg.Agent)
	}
	if len(cat.users) != 1 || cat.users[0] != p.UserID {
		t.Fatalf("catalog asked for %v", cat.users)
	}
}

func TestResolveRunConfigFailsFinallyWhenNoAgentOrCatalogItemHasTheID(t *testing.T) {
	p := testPrincipal()
	_, err := catalogRunService(&catalogRunAgents{}).ResolveRunConfig(context.Background(), p, ResolveInput{ModelOverride: "model-1"})
	var app *durable.ApplicationError
	if !errors.As(err, &app) || !app.NonRetryable || app.Type != "AgentNotFoundError" {
		t.Fatalf("missing agent: %v", err)
	}
}

func TestResolveRunConfigFailsFinallyWhenThePolicyRefusesTheCatalogAgent(t *testing.T) {
	p := testPrincipal()
	_, err := catalogRunService(&catalogRunAgents{refus: "Install refused by policy: no community"}).
		ResolveRunConfig(context.Background(), p, ResolveInput{ModelOverride: "model-1"})
	var app *durable.ApplicationError
	if !errors.As(err, &app) || !app.NonRetryable || app.Message != "Install refused by policy: no community" {
		t.Fatalf("refused agent: %v", err)
	}
}
