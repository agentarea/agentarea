package agents

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/service"
)

// MiscDeps are the ports of GET /agents/tools, the presets, install and the export.
type MiscDeps = service.MiscDeps

// misc builds the route group over the MiscDeps in Deps.
func (m *Module) misc() *service.Misc {
	d := m.d.MiscDeps
	if d.ExportSkills == nil {
		d.ExportSkills = service.SkillsExport{K: m.skills()}
	}
	if d.AgentCatalog == nil && m.d.CatalogItems != nil {
		d.AgentCatalog = service.CatalogAgents{S: m.svc, Items: m.d.CatalogItems, Policy: m.d.SkillInstallPolicy}
	}
	return service.NewMisc(m.svc, d)
}

// UseExport sets the ports of the workspace config export that other modules provide.
func (m *Module) UseExport(w service.ExportWorkspaces, mcps service.ExportMCPs, triggers service.ExportTriggers) {
	m.d.ExportWorkspaces, m.d.ExportMCPs, m.d.ExportTriggers = w, mcps, triggers
}

// UseToolsMCP sets the MCP tools GET /agents/tools lists (connections module).
func (m *Module) UseToolsMCP(t service.ToolsMCP) { m.d.ToolsMCP = t }

// WorkspaceConfig is what the workspace_config toolset calls; nil without a full graph.
// It reads the export ports at call time, after UseExport.
func (m *Module) WorkspaceConfig() api.WorkspaceConfig {
	if m.svc == nil {
		return nil
	}
	return lateWorkspaceConfig{m: m}
}

type lateWorkspaceConfig struct{ m *Module }

func (l lateWorkspaceConfig) Export(ctx context.Context, c authn.Caller) (string, error) {
	return l.m.misc().Export(ctx, c)
}
