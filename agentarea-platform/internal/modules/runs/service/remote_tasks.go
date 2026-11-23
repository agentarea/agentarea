package service

import (
	"context"
	"errors"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

var errRemoteTasksUnwired = errors.New("the remote delegates' tasks are not wired")

func remoteTaskInvocation(p Principal, in ToolCall) ToolInvocation {
	return ToolInvocation{
		Principal: p, TaskID: in.TaskID, ExecutionID: in.ExecutionID, WorkflowID: in.WorkflowID, ToolCallID: in.ToolCallID,
		ToolName: in.ToolName, Args: in.Args, Binding: in.Binding, RunMetadata: in.RunMetadata, CallRef: callRef(in),
	}
}

// GetRemoteTask reads the task a remote delegate call started, once. Its answer, once
// the task ended, is kept as a tool's is.
func (s *Service) GetRemoteTask(ctx context.Context, p Principal, in ToolCall, task api.RemoteAgentTask) (ToolResult, error) {
	if s.d.RemoteTasks == nil {
		return ToolResult{}, errRemoteTasksUnwired
	}
	out, err := s.d.RemoteTasks.GetTask(ctx, remoteTaskInvocation(p, in), task)
	if err != nil || out.RemoteTask != nil {
		return ToolResult{Out: out}, err
	}
	res := ToolResult{Out: out}
	res.Images, res.Out.Result, err = s.keepOutput(ctx, p, in, out)
	return res, err
}

// CancelRemoteTask asks the remote delegate to stop the task a call started.
func (s *Service) CancelRemoteTask(ctx context.Context, p Principal, in ToolCall, task api.RemoteAgentTask) error {
	if s.d.RemoteTasks == nil {
		return errRemoteTasksUnwired
	}
	return s.d.RemoteTasks.CancelTask(ctx, remoteTaskInvocation(p, in), task)
}
