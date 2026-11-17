package app

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	identitydomain "github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
	identityservice "github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/service"
)

// explorerResources are the access explorer's reads: agents, skills and
// collections from agents, MCP server specs from catalog.
type explorerResources struct {
	lookup    agentsapi.Lookup
	inventory agentsapi.Inventory
	mcp       catalogapi.MCPInventory
}

var _ identityservice.Resources = explorerResources{}

func (r explorerResources) Exists(ctx context.Context, ws scope.Workspace, namespace string, id uuid.UUID) (bool, error) {
	switch namespace {
	case identitydomain.NamespaceAgent:
		return r.lookup.AgentExists(ctx, ws, id.String())
	case identitydomain.NamespaceSkill:
		return r.lookup.SkillExists(ctx, ws, id.String())
	case identitydomain.NamespaceSkillCollection:
		return r.inventory.CollectionExists(ctx, ws, id)
	case identitydomain.NamespaceMCPServer:
		return r.mcp.MCPServerExists(ctx, ws, id)
	}
	return false, fmt.Errorf("explorer: unknown namespace %q", namespace)
}

func named(list []agentsapi.Named, err error) ([]identityservice.Named, error) {
	if err != nil {
		return nil, err
	}
	out := make([]identityservice.Named, len(list))
	for i, n := range list {
		out[i] = identityservice.Named{ID: n.ID, Name: n.Name}
	}
	return out, nil
}

func (r explorerResources) Agents(ctx context.Context, ws scope.Workspace, includeArchived bool) ([]identityservice.Named, error) {
	return named(r.inventory.Agents(ctx, ws, includeArchived))
}

func (r explorerResources) Collections(ctx context.Context, ws scope.Workspace) ([]identityservice.Named, error) {
	return named(r.inventory.Collections(ctx, ws))
}

func (r explorerResources) SkillCounts(ctx context.Context, ws scope.Workspace) (map[string]int, error) {
	return r.inventory.SkillCounts(ctx, ws)
}

func (r explorerResources) Skills(ctx context.Context, ws scope.Workspace) ([]identityservice.Named, error) {
	return named(r.inventory.Skills(ctx, ws))
}

func (r explorerResources) MCPServers(ctx context.Context, ws scope.Workspace) ([]identityservice.Named, error) {
	list, err := r.mcp.MCPServers(ctx, ws)
	if err != nil {
		return nil, err
	}
	out := make([]identityservice.Named, len(list))
	for i, n := range list {
		out[i] = identityservice.Named{ID: n.ID, Name: n.Name}
	}
	return out, nil
}

// lateMCPInventory is catalog's MCP inventory for identity, which is built first.
type lateMCPInventory struct{ m *moduleSet }

func (l lateMCPInventory) MCPServers(ctx context.Context, ws scope.Workspace) ([]catalogapi.MCPServer, error) {
	return l.m.catalog.MCPInventory().MCPServers(ctx, ws)
}

func (l lateMCPInventory) MCPServerExists(ctx context.Context, ws scope.Workspace, id uuid.UUID) (bool, error) {
	return l.m.catalog.MCPInventory().MCPServerExists(ctx, ws, id)
}
