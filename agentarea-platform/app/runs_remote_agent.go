package app

import (
	"context"
	"fmt"
	"strings"

	"github.com/google/uuid"

	connectionsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	runsservice "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/service"
)

// remoteAgentCaller runs a run's remote A2A delegate calls through connections: the send as
// the call, then the task it starts read and stopped by the run. A failure the tool raised
// answers as execute_mcp_tool_activity renders a ToolExecutionError.
type remoteAgentCaller struct{ t connectionsapi.RemoteAgents }

func (c remoteAgentCaller) Call(ctx context.Context, inv runsservice.ToolInvocation) (runsservice.ToolOutput, error) {
	b := inv.Binding.RemoteAgent
	if b == nil {
		return runsservice.ToolOutput{}, fmt.Errorf("tool %s is bound to remote_agent without an address", inv.ToolName)
	}
	message, _ := inv.Args["message"].(string)
	paid := paidCall(inv)
	r, err := c.t.SendRemoteAgent(ctx, connectionsapi.RemoteAgentCall{
		WorkspaceID: inv.Principal.WorkspaceID, UserID: inv.Principal.UserID, AgentID: inv.Principal.AgentID,
		AgentName: b.AgentName, ToolName: inv.ToolName, ToolCallID: inv.ToolCallID, A2AURL: b.A2AURL,
		AuthSecretName: b.AuthSecretName, Message: message, MessageID: remoteMessageID(paid.ExecutionID, inv.ToolCallID), Paid: paid,
	})
	if err != nil {
		return runsservice.ToolOutput{}, err
	}
	out := remoteOutput(inv.ToolName, r)
	out.Payments, out.ServiceCost = toolPayments(r.Payments)
	return out, nil
}

func (c remoteAgentCaller) GetTask(ctx context.Context, inv runsservice.ToolInvocation, task runsapi.RemoteAgentTask) (runsservice.ToolOutput, error) {
	call, err := remoteTaskCall(inv, task)
	if err != nil {
		return runsservice.ToolOutput{}, err
	}
	r, err := c.t.GetRemoteAgentTask(ctx, call)
	if err != nil {
		return runsservice.ToolOutput{}, err
	}
	return remoteOutput(inv.ToolName, r), nil
}

func (c remoteAgentCaller) CancelTask(ctx context.Context, inv runsservice.ToolInvocation, task runsapi.RemoteAgentTask) error {
	call, err := remoteTaskCall(inv, task)
	if err != nil {
		return err
	}
	return c.t.CancelRemoteAgentTask(ctx, call)
}

// remoteMessageID is the A2A messageId of one call: the same on every attempt of it.
func remoteMessageID(executionID, toolCallID string) string {
	id := uuid.NewSHA1(uuid.NameSpaceURL, []byte("agentarea:a2a-message:"+executionID+":"+toolCallID))
	return strings.ReplaceAll(id.String(), "-", "")
}

func remoteTaskCall(inv runsservice.ToolInvocation, task runsapi.RemoteAgentTask) (connectionsapi.RemoteTaskCall, error) {
	b := inv.Binding.RemoteAgent
	if b == nil {
		return connectionsapi.RemoteTaskCall{}, fmt.Errorf("tool %s is bound to remote_agent without an address", inv.ToolName)
	}
	return connectionsapi.RemoteTaskCall{
		WorkspaceID: inv.Principal.WorkspaceID, UserID: inv.Principal.UserID, AgentName: b.AgentName, A2AURL: b.A2AURL,
		AuthSecretName: b.AuthSecretName, Task: connectionsapi.RemoteTask{ID: task.TaskID, Endpoint: task.Endpoint, Legacy: task.Legacy},
	}, nil
}

func remoteOutput(tool string, r connectionsapi.RemoteAgentResult) runsservice.ToolOutput {
	if r.Pending != nil {
		return runsservice.ToolOutput{Success: true, Source: "builtin",
			RemoteTask: &runsapi.RemoteAgentTask{TaskID: r.Pending.ID, Endpoint: r.Pending.Endpoint, Legacy: r.Pending.Legacy}}
	}
	out := runsservice.ToolOutput{Success: r.Success, Result: r.Result, Error: r.Error, Source: "builtin"}
	if r.Raised {
		msg := fmt.Sprintf("Tool '%s' execution failed: %s", tool, r.Error)
		out.Result, out.Error = "MCP tool error: ToolExecutionError: "+msg, msg
	}
	return out
}
