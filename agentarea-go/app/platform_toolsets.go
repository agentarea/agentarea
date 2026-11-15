package app

import (
	"context"

	kscope "github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections"
)

// platformToolsets are the providers of every platform toolset, the one
// registry /mcp, /mcp/w/{workspace}, client bundles and runs share.
// useLateToolsets sets those of modules built after connections.
func (m *moduleSet) platformToolsets() *connections.Toolsets {
	specs := m.catalog.SpecLists()
	m.toolsets = &connections.Toolsets{
		Agents: m.agents.AgentsToolset(), TaskDefs: m.agents.TaskDefsToolset(), Skills: m.agents.SkillsToolset(),
		Clients: m.agents.ClientsToolset(), WorkspaceConfig: m.agents.WorkspaceConfig(), Members: m.identity.Members(),
		Files: m.sandbox.Files(), Slugs: m.identity.WorkspaceSlugs(),
		Projects: m.projects.PlatformProjects(), Policies: m.governance.PlatformPolicies(), Audit: m.governance.PlatformAudit(),
		WorkspaceFiles: m.sandbox.PlatformFiles(),
		LLMProviders:   m.models.PlatformProviders(specs), Models: m.models.PlatformModels(specs),
		OpenAPI: m.connections.PlatformOpenAPI(), MCPServers: m.connections.PlatformMCPServers(),
		ConnectorTools: m.connections.PlatformConnectorTools(),
	}
	if s := m.governance.PlatformSecrets(); s != nil {
		m.toolsets.Secrets = s
	}
	return m.toolsets
}

func (m *moduleSet) useLateToolsets() {
	t := m.toolsets
	t.Runs, t.Inbox = m.runsSurface.PlatformRuns(), m.runsSurface.PlatformInbox()
	t.Triggers, t.Streams, t.StreamEvents = m.streams.PlatformTriggers(), m.streams.PlatformStreams(), m.streams.PlatformStreamEvents()
	t.Network = m.insights.PlatformNetwork()
}

// lateTaskMetadata is runs' task metadata for governance, built first.
type lateTaskMetadata struct{ m *moduleSet }

func (t lateTaskMetadata) TaskMetadata(ctx context.Context, ws kscope.Workspace, taskID string) ([]byte, bool, error) {
	return t.m.runsSurface.TaskMetadata(ctx, ws, taskID)
}
