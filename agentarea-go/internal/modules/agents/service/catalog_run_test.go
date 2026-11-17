package service

import (
	"context"
	"errors"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	govapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
)

type runBindConnections struct {
	createFakeConnections
	bound   map[string]string
	refused []bool
}

func (f *runBindConnections) BindMCPName(_ context.Context, _ authn.Caller, name string, refuseUnbound bool) (string, error) {
	f.refused = append(f.refused, refuseUnbound)
	return f.bound[name], nil
}

type runPolicyBy struct {
	runFakePolicy
	users []string
	deny  bool
}

func (p *runPolicyBy) RequireAllowed(_ context.Context, c authn.Caller, _, _ string) error {
	p.users = append(p.users, c.UserID)
	if p.deny {
		return &govapi.InstallRefusedError{Reason: "community registries are not allowed"}
	}
	return nil
}

func TestCatalogDefinitionRunsAnUninstalledCatalogAgentFromItsDefinition(t *testing.T) {
	ctx := context.Background()
	_, _, s, c := clientSetup(t)
	conns := &runBindConnections{bound: map[string]string{"github": "11111111-2222-3333-4444-555555555555"}}
	s.UseConnections(conns)
	item := agentItem("Researcher", `{"instruction":"Find things","description":"From spec","planning":true,
		"tools":[{"type":"mcp","name":"github"},{"type":"code","name":"agentarea/files"}]}`)
	items := &agentFakeItems{agents: map[string]catalogapi.CatalogItem{item.ID: item}}
	policy := &runPolicyBy{}
	x := CatalogRun{S: s, Items: items, Policy: policy}

	def, err := x.CatalogDefinition(ctx, c.Workspace, "starter", item.ID)
	if err != nil {
		t.Fatal(err)
	}
	if def.ID != item.ID || def.Name != "Researcher" || def.Instruction != "Find things" || def.Description != "From spec" ||
		!def.Planning || def.AgentType != "stateless" || def.ModelID != "" || def.Archived || def.RegistryItemID != item.ID || len(def.Skills) != 0 {
		t.Fatalf("definition %+v", def)
	}
	if len(def.Tools) != 2 || def.Tools[0].Name != "11111111-2222-3333-4444-555555555555" || def.Tools[1].Name != "agentarea/files" {
		t.Fatalf("tools %+v", def.Tools)
	}
	if len(conns.refused) != 1 || conns.refused[0] {
		t.Fatalf("binding refused unbound names: %v", conns.refused)
	}
	if len(policy.users) != 1 || policy.users[0] != "starter" {
		t.Fatalf("policy asked for %v", policy.users)
	}
	if len(items.marked) != 0 {
		t.Fatalf("a run installed the agent: %v", items.marked)
	}

	if _, err := x.CatalogDefinition(ctx, c.Workspace, "starter", uuid.NewString()); !errors.Is(err, api.ErrNotFound) {
		t.Fatalf("unknown item: %v", err)
	}
	if _, err := x.CatalogDefinition(ctx, c.Workspace, "starter", "not-a-uuid"); !errors.Is(err, api.ErrNotFound) {
		t.Fatalf("not an id: %v", err)
	}
	policy.deny = true
	_, err = x.CatalogDefinition(ctx, c.Workspace, "starter", item.ID)
	var refused *api.AgentRefusedError
	if !errors.As(err, &refused) || refused.Msg != "Install refused by policy: community registries are not allowed" {
		t.Fatalf("refused: %v", err)
	}
}
