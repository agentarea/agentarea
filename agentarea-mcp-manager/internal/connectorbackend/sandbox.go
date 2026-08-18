package connectorbackend

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/agentarea/mcp-manager/internal/connectorhub"
	"github.com/agentarea/mcp-manager/internal/connectorproto"
	"github.com/agentarea/mcp-manager/internal/sandboxplacement"
	"github.com/agentarea/mcp-manager/internal/warmpool"
)

// SandboxExecutor sends manager-owned sandbox commands to a pinned connector.
// The execution identity is carried separately in the operation envelope and
// used as the hub operation ID, so an acknowledged execution remains tied to
// the same connector-side id through reconciliation.
type SandboxExecutor struct {
	hub         OperationHub
	dataPlaneID string
}

var _ sandboxplacement.Executor = (*SandboxExecutor)(nil)

func NewSandboxExecutor(hub OperationHub, dataPlaneID string) (*SandboxExecutor, error) {
	if hub == nil {
		return nil, fmt.Errorf("connector hub is required")
	}
	if strings.TrimSpace(dataPlaneID) == "" {
		return nil, fmt.Errorf("data_plane_id is required")
	}
	return &SandboxExecutor{hub: hub, dataPlaneID: dataPlaneID}, nil
}

// Execute sends an explicitly identified execution. It is useful at control
// plane boundaries that retain an execution record. ExecuteSandbox below uses
// WorkflowID, which sandboxrunner guarantees to be the execution identity when
// no workflow id was supplied.
func (e *SandboxExecutor) Execute(ctx context.Context, executionID string, req warmpool.ExecuteRequest) (*warmpool.ExecuteResponse, error) {
	if strings.TrimSpace(executionID) == "" {
		return nil, fmt.Errorf("execution ID is required")
	}
	payload, err := json.Marshal(struct {
		ExecutionID string                  `json:"execution_id"`
		Request     warmpool.ExecuteRequest `json:"request"`
	}{ExecutionID: executionID, Request: req})
	if err != nil {
		return nil, fmt.Errorf("encode sandbox execute payload: %w", err)
	}
	result, err := e.hub.StartOperation(ctx, e.dataPlaneID, connectorhub.OperationRequest{
		ID:          executionID,
		Kind:        operationKind(connectorproto.OperationKind_OPERATION_KIND_SANDBOX_EXECUTE),
		Payload:     payload,
		ContentType: "application/json",
	})
	if err != nil {
		return nil, err
	}
	if result == nil || result.Status != connectorhub.ResultSucceeded {
		if result == nil {
			return nil, fmt.Errorf("%w: connector returned no sandbox result", ErrOperationFailed)
		}
		return nil, connectorResultError(result)
	}
	var response warmpool.ExecuteResponse
	if err := json.Unmarshal(result.Payload, &response); err != nil {
		return nil, fmt.Errorf("decode sandbox execute response: %w", err)
	}
	return &response, nil
}

func (e *SandboxExecutor) ExecuteSandbox(ctx context.Context, req warmpool.ExecuteRequest) (*warmpool.ExecuteResponse, error) {
	return e.Execute(ctx, req.WorkflowID, req)
}
