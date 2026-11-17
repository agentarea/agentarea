package app

import (
	"context"
	"fmt"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	agentsservice "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
	connectionsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	identityapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/api"
	streamsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/api"
)

// exportWorkspaces names the caller's workspace from identity's workspace list.
type exportWorkspaces struct{ m identityapi.Members }

var _ agentsservice.ExportWorkspaces = exportWorkspaces{}

func (e exportWorkspaces) WorkspaceName(ctx context.Context, c authn.Caller) (string, error) {
	all, err := e.m.ListWorkspaces(ctx, c.Principal)
	if err != nil {
		return "", err
	}
	for _, w := range all {
		if w.ID == c.Workspace.ID() {
			return w.Name, nil
		}
	}
	return "", fmt.Errorf("Workspace %s does not exist", c.Workspace.ID())
}

// exportMCPs is connections' instance list as the export reads it.
type exportMCPs struct{ x connectionsapi.MCPExports }

var _ agentsservice.ExportMCPs = exportMCPs{}

func (e exportMCPs) ExportInstances(ctx context.Context, c authn.Caller) ([]agentsservice.ExportMCPInstance, error) {
	got, err := e.x.ExportInstances(ctx, c)
	if err != nil {
		return nil, err
	}
	out := make([]agentsservice.ExportMCPInstance, len(got))
	for i, g := range got {
		out[i] = agentsservice.ExportMCPInstance{ID: g.ID, Name: g.Name, Spec: g.Spec, EnvVars: g.EnvVars, ContextSigning: g.ContextSigning}
		if g.Platform {
			out[i].ManagedBy = "platform"
		}
	}
	return out, nil
}

// exportTriggers is streams' trigger list as the export reads it.
type exportTriggers struct{ x streamsapi.TriggerExports }

var _ agentsservice.ExportTriggers = exportTriggers{}

func (e exportTriggers) ExportTriggers(ctx context.Context, c authn.Caller) ([]agentsservice.ExportTriggerRow, error) {
	got, err := e.x.ExportTriggers(ctx, c.Workspace)
	if err != nil {
		return nil, err
	}
	out := make([]agentsservice.ExportTriggerRow, len(got))
	for i, g := range got {
		row := agentsservice.ExportTriggerRow{ID: g.ID, Name: g.Name, TriggerType: g.TriggerType, AgentID: g.AgentID,
			Conditions: len(g.Conditions) > 0, TaskParameters: wirejson.Object{}, CronExpression: g.CronExpression, Timezone: g.Timezone, IsActive: g.IsActive}
		if text, ok := g.TaskParameters["text"]; ok {
			row.TaskParameters = wirejson.Object{{Key: "text", Value: text}}
		}
		out[i] = row
	}
	return out, nil
}

// toolsMCP is connections' MCP tool catalogue as GET /agents/tools reads it.
type toolsMCP struct {
	x connectionsapi.MCPToolCatalogue
}

var _ agentsservice.ToolsMCP = toolsMCP{}

func (t toolsMCP) InstanceTools(ctx context.Context, c authn.Caller, instanceID string) ([]agentsservice.ToolsMCPInstance, error) {
	got, err := t.x.ToolInstances(ctx, c, instanceID)
	if err != nil {
		return nil, err
	}
	out := make([]agentsservice.ToolsMCPInstance, len(got))
	for i, g := range got {
		out[i] = agentsservice.ToolsMCPInstance{ID: g.ID, Name: g.Name, Tools: g.Tools}
	}
	return out, nil
}
