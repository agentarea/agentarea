package app

import (
	"context"
	"encoding/json"
	"errors"

	connectionsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	runsservice "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/service"
)

// platformCaller runs a run's code tools of a platform namespace through
// connections' platform toolset registry; any other code namespace is unknown.
type platformCaller struct{ t connectionsapi.PlatformTools }

func (c platformCaller) Call(ctx context.Context, inv runsservice.ToolInvocation) (runsservice.ToolOutput, error) {
	unknown := runsservice.ToolOutput{Result: "MCP tool error: Unknown tool: " + inv.ToolName, Error: "Unknown tool: " + inv.ToolName, Source: "builtin"}
	b := inv.Binding.Code
	if b == nil {
		return unknown, nil
	}
	args, err := json.Marshal(inv.Args)
	if err != nil {
		return runsservice.ToolOutput{}, err
	}
	r, err := c.t.Call(ctx, connectionsapi.PlatformCall{
		WorkspaceID: inv.Principal.WorkspaceID, UserID: inv.Principal.UserID, AgentID: inv.Principal.AgentID,
		Namespace: b.Namespace, Method: b.Method, Args: args,
	})
	if errors.Is(err, connectionsapi.ErrUnknownPlatformTool) {
		return unknown, nil
	}
	if err != nil {
		return runsservice.ToolOutput{}, err
	}
	out := runsservice.ToolOutput{Success: !r.IsError, Result: r.Text, Source: "builtin", StructuredContent: r.StructuredContent}
	if r.IsError {
		out.Error, out.StructuredContent = r.Text, nil
	}
	return out, nil
}
