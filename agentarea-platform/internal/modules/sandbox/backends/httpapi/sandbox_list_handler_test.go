package httpapi

import (
	"context"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/sandboxruntime"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/warmpool"
)

type inventorySandboxRuntime struct {
	controlRuntimeStub
	workspaceID string
}

func (r *inventorySandboxRuntime) ExecuteSandbox(context.Context, warmpool.ExecuteRequest) (*warmpool.ExecuteResponse, error) {
	return nil, nil
}
func (r *inventorySandboxRuntime) SandboxFilePut(context.Context, warmpool.FilePutRequest) (*warmpool.FilePutResponse, error) {
	return nil, nil
}
func (r *inventorySandboxRuntime) SandboxFileGet(context.Context, string, string, string) (*warmpool.FileGetResponse, error) {
	return nil, nil
}
func (r *inventorySandboxRuntime) SandboxFileList(context.Context, string, string, string) (*warmpool.FileListResponse, error) {
	return nil, nil
}
func (r *inventorySandboxRuntime) ListSandboxes(_ context.Context, workspaceID string) ([]sandboxruntime.SandboxStatus, error) {
	r.workspaceID = workspaceID
	return []sandboxruntime.SandboxStatus{{
		ID:          "sandbox-1",
		Provider:    "opensandbox",
		WorkspaceID: workspaceID,
		TaskID:      "task-1",
		State:       "running",
		Resources:   map[string]string{"cpu": "500m", "memory": "512Mi"},
		Isolation:   "gvisor",
	}}, nil
}

func TestSandboxInventoryRequiresInspectionSecret(t *testing.T) {
	recorder := httptest.NewRecorder()
	context := &reqctx{Writer: recorder}
	context.Request = httptest.NewRequest(http.MethodGet, "/sandbox/sessions?workspace_id=workspace-1", nil)
	context.Request.Header.Set("Authorization", "Bearer anything")

	(&Handler{logger: slog.Default()}).listSandboxes(context)

	if recorder.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want 401; body=%s", recorder.Code, recorder.Body.String())
	}
}

func TestSandboxInventoryScopesProviderQuery(t *testing.T) {
	runtime := &inventorySandboxRuntime{}
	recorder := httptest.NewRecorder()
	context := &reqctx{Writer: recorder}
	context.Request = httptest.NewRequest(http.MethodGet, "/sandbox/sessions?workspace_id=workspace-1", nil)
	context.Request.Header.Set("Authorization", "Bearer inspection-secret")

	(&Handler{secrets: Secrets{Inspect: "inspection-secret"}, logger: slog.Default(), sandboxRuntime: runtime}).listSandboxes(context)

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", recorder.Code, recorder.Body.String())
	}
	if runtime.workspaceID != "workspace-1" {
		t.Fatalf("workspace = %q, want workspace-1", runtime.workspaceID)
	}
	if got := recorder.Body.String(); got == "" || got == `{"items":[],"total":0}` {
		t.Fatalf("body = %s, want live inventory", got)
	}
}
