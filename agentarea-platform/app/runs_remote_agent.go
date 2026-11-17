package app

import (
	"context"
	"fmt"

	connectionsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	runsservice "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/service"
)

// remoteAgentCaller runs a run's remote A2A delegate calls through connections. A failure
// the tool raised answers as execute_mcp_tool_activity renders a ToolExecutionError.
type remoteAgentCaller struct{ t connectionsapi.RemoteAgents }

func (c remoteAgentCaller) Call(ctx context.Context, inv runsservice.ToolInvocation) (runsservice.ToolOutput, error) {
	b := inv.Binding.RemoteAgent
	if b == nil {
		return runsservice.ToolOutput{}, fmt.Errorf("tool %s is bound to remote_agent without an address", inv.ToolName)
	}
	message, _ := inv.Args["message"].(string)
	r, err := c.t.CallRemoteAgent(ctx, connectionsapi.RemoteAgentCall{
		WorkspaceID: inv.Principal.WorkspaceID, UserID: inv.Principal.UserID, AgentID: inv.Principal.AgentID,
		AgentName: b.AgentName, ToolName: inv.ToolName, ToolCallID: inv.ToolCallID, A2AURL: b.A2AURL,
		AuthSecretName: b.AuthSecretName, Message: message, Paid: paidCall(inv),
	})
	if err != nil {
		return runsservice.ToolOutput{}, err
	}
	out := runsservice.ToolOutput{Success: r.Success, Result: r.Result, Error: r.Error, Source: "builtin"}
	if r.Raised {
		msg := fmt.Sprintf("Tool '%s' execution failed: %s", inv.ToolName, r.Error)
		out.Result, out.Error = "MCP tool error: ToolExecutionError: "+msg, msg
	}
	out.Payments, out.ServiceCost = toolPayments(r.Payments)
	return out, nil
}
