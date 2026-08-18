package connectorbackend

// This file supplies the narrow sandbox HTTP control port for a connector
// placement. Durable execution records remain in the manager's Redis store;
// only data-plane work crosses the outbound connector.

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"time"

	"github.com/agentarea/mcp-manager/internal/connectorhub"
	"github.com/agentarea/mcp-manager/internal/connectorproto"
	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/sandboxcontract"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime"
)

// ControlRuntime implements the HTTP-facing sandbox file and retirement port
// over one pinned connector. It intentionally does not implement ManagedRuntime:
// lifecycle persistence and scheduling belong to the control-plane runner.
type ControlRuntime struct {
	hub         OperationHub
	dataPlaneID string
}

var _ sandboxruntime.ControlRuntime = (*ControlRuntime)(nil)

func NewControlRuntime(hub OperationHub, dataPlaneID string) (*ControlRuntime, error) {
	if hub == nil {
		return nil, fmt.Errorf("connector hub is required")
	}
	if strings.TrimSpace(dataPlaneID) == "" {
		return nil, fmt.Errorf("data_plane_id is required")
	}
	return &ControlRuntime{hub: hub, dataPlaneID: dataPlaneID}, nil
}

func (r *ControlRuntime) PutWorkspaceFile(ctx context.Context, request sandboxcontract.FilePutRequest) (*sandboxcontract.FilePutResponse, error) {
	var response sandboxcontract.FilePutResponse
	if err := r.call(ctx, connectorproto.OperationKind_OPERATION_KIND_SANDBOX_FILE_PUT, request, &response); err != nil {
		return nil, err
	}
	return &response, nil
}

func (r *ControlRuntime) GetWorkspaceFile(ctx context.Context, request sandboxruntime.WorkspaceFileRead) (*sandboxcontract.FileGetResponse, error) {
	var response sandboxcontract.FileGetResponse
	if err := r.call(ctx, connectorproto.OperationKind_OPERATION_KIND_SANDBOX_FILE_GET, struct {
		WorkspaceID string `json:"workspace_id"`
		TaskID      string `json:"task_id"`
		Path        string `json:"path"`
	}{request.WorkspaceID, request.TaskID, request.Path}, &response); err != nil {
		return nil, err
	}
	return &response, nil
}

func (r *ControlRuntime) OpenWorkspaceFile(ctx context.Context, request sandboxruntime.WorkspaceFileRead) (*sandboxruntime.FileDownload, error) {
	response, err := r.GetWorkspaceFile(ctx, request)
	if err != nil {
		return nil, err
	}
	content, err := base64.StdEncoding.DecodeString(response.ContentBase64)
	if err != nil {
		return nil, fmt.Errorf("decode connector sandbox file: %w", err)
	}
	return &sandboxruntime.FileDownload{Content: io.NopCloser(bytes.NewReader(content)), Size: int64(len(content)), Mode: 0o600}, nil
}

func (r *ControlRuntime) ListWorkspaceFiles(ctx context.Context, request sandboxruntime.WorkspaceFileList) (*sandboxcontract.FileListResponse, error) {
	var response sandboxcontract.FileListResponse
	if err := r.call(ctx, connectorproto.OperationKind_OPERATION_KIND_SANDBOX_FILE_LIST, struct {
		WorkspaceID string `json:"workspace_id"`
		TaskID      string `json:"task_id"`
		Prefix      string `json:"prefix"`
	}{request.WorkspaceID, request.TaskID, request.Prefix}, &response); err != nil {
		return nil, err
	}
	return &response, nil
}

func (r *ControlRuntime) UploadWorkspaceFile(ctx context.Context, request sandboxruntime.FileUpload, content io.Reader) (*sandboxruntime.FileWriteResult, error) {
	body, err := io.ReadAll(io.LimitReader(content, request.Size+1))
	if err != nil {
		return nil, fmt.Errorf("read sandbox upload: %w", err)
	}
	if int64(len(body)) != request.Size {
		return nil, fmt.Errorf("sandbox upload size does not match declared size")
	}
	response, err := r.PutWorkspaceFile(ctx, sandboxcontract.FilePutRequest{WorkspaceID: request.WorkspaceID, TaskID: request.TaskID, Path: request.Path, ContentBase64: base64.StdEncoding.EncodeToString(body)})
	if err != nil {
		return nil, err
	}
	return &sandboxruntime.FileWriteResult{Path: response.Path, Size: response.Size}, nil
}

func (r *ControlRuntime) RetireSandboxTask(ctx context.Context, workspaceID, taskID string, idleTTL time.Duration) error {
	return r.call(ctx, connectorproto.OperationKind_OPERATION_KIND_SANDBOX_TASK_RETIRE, struct {
		WorkspaceID string `json:"workspace_id"`
		TaskID      string `json:"task_id"`
		IdleTTL     string `json:"idle_ttl,omitempty"`
	}{workspaceID, taskID, idleTTL.String()}, &struct{}{})
}

func (r *ControlRuntime) RuntimeManifest(context.Context) (*runtimeinfo.Manifest, error) {
	return nil, fmt.Errorf("connector runtime manifest is not available")
}

func (r *ControlRuntime) call(ctx context.Context, kind connectorproto.OperationKind, input, output any) error {
	payload, err := json.Marshal(input)
	if err != nil {
		return err
	}
	result, err := r.hub.StartOperation(ctx, r.dataPlaneID, connectorhub.OperationRequest{Kind: kind.String(), Payload: payload, ContentType: "application/json"})
	if err != nil {
		return err
	}
	if result == nil {
		return fmt.Errorf("connector returned no sandbox result")
	}
	if result.Status != connectorhub.ResultSucceeded {
		return connectorResultError(result)
	}
	if err := json.Unmarshal(result.Payload, output); err != nil {
		return fmt.Errorf("decode connector sandbox response: %w", err)
	}
	return nil
}
