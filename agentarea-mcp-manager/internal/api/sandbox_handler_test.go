package api

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/artifactstore"
	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime"
	"github.com/agentarea/mcp-manager/internal/warmpool"
	"github.com/gin-gonic/gin"
)

type retiringSandboxRuntime struct {
	controlRuntimeStub
	workspaceID string
	taskID      string
	ttl         time.Duration
	filePut     *warmpool.FilePutRequest
	streamPut   *sandboxruntime.FileUpload
	streamBody  []byte
	fileRead    *sandboxruntime.WorkspaceFileRead
}

type recordingArtifactStore struct {
	published []byte
	artifact  artifactstore.Artifact
	openBody  io.ReadCloser
	openErr   error
}

func (s *recordingArtifactStore) PublishStream(
	_ context.Context,
	_, _, sourcePath, contentType string,
	source io.Reader,
	size int64,
) (artifactstore.Artifact, error) {
	content, err := io.ReadAll(source)
	if err != nil {
		return artifactstore.Artifact{}, err
	}
	s.published = content
	return artifactstore.Artifact{
		ID: "art_0123456789abcdef0123456789abcdef", Path: sourcePath, Name: sourcePath,
		Size: size, ContentType: contentType,
	}, nil
}

func (s *recordingArtifactStore) List(context.Context, string, string) ([]artifactstore.Artifact, error) {
	return nil, nil
}

func (s *recordingArtifactStore) Open(context.Context, string, string, string) (artifactstore.Artifact, io.ReadCloser, error) {
	if s.openBody != nil || s.openErr != nil {
		return s.artifact, s.openBody, s.openErr
	}
	return artifactstore.Artifact{}, nil, artifactstore.ErrArtifactNotFound
}

type eofFailureReadCloser struct {
	reader *bytes.Reader
	err    error
}

func (r *eofFailureReadCloser) Read(buffer []byte) (int, error) {
	if r.reader.Len() == 0 {
		return 0, r.err
	}
	return r.reader.Read(buffer)
}

func (*eofFailureReadCloser) Close() error { return nil }

func (r *retiringSandboxRuntime) ExecuteSandbox(context.Context, warmpool.ExecuteRequest) (*warmpool.ExecuteResponse, error) {
	return nil, nil
}
func (r *retiringSandboxRuntime) SandboxFilePut(_ context.Context, req warmpool.FilePutRequest) (*warmpool.FilePutResponse, error) {
	r.filePut = &req
	return &warmpool.FilePutResponse{Path: req.Path}, nil
}
func (r *retiringSandboxRuntime) PutWorkspaceFile(ctx context.Context, req warmpool.FilePutRequest) (*warmpool.FilePutResponse, error) {
	return r.SandboxFilePut(ctx, req)
}
func (r *retiringSandboxRuntime) SandboxFileGet(context.Context, string, string, string) (*warmpool.FileGetResponse, error) {
	return &warmpool.FileGetResponse{}, nil
}
func (r *retiringSandboxRuntime) SandboxFileUpload(_ context.Context, req sandboxruntime.FileUpload, source io.Reader) (*sandboxruntime.FileWriteResult, error) {
	content, err := io.ReadAll(source)
	if err != nil {
		return nil, err
	}
	r.streamPut = &req
	r.streamBody = content
	return &sandboxruntime.FileWriteResult{Path: req.Path, Size: int64(len(content))}, nil
}
func (r *retiringSandboxRuntime) UploadWorkspaceFile(ctx context.Context, req sandboxruntime.FileUpload, source io.Reader) (*sandboxruntime.FileWriteResult, error) {
	return r.SandboxFileUpload(ctx, req, source)
}
func (r *retiringSandboxRuntime) SandboxFileDownload(context.Context, string, string, string) (*sandboxruntime.FileDownload, error) {
	return &sandboxruntime.FileDownload{Content: io.NopCloser(bytes.NewReader(r.streamBody)), Size: int64(len(r.streamBody)), Mode: 0o600}, nil
}
func (r *retiringSandboxRuntime) SandboxFileList(context.Context, string, string, string) (*warmpool.FileListResponse, error) {
	return nil, nil
}
func (r *retiringSandboxRuntime) RuntimeManifest(context.Context) (*runtimeinfo.Manifest, error) {
	return nil, nil
}

func (r *retiringSandboxRuntime) GetWorkspaceFile(_ context.Context, req sandboxruntime.WorkspaceFileRead) (*warmpool.FileGetResponse, error) {
	r.fileRead = &req
	return &warmpool.FileGetResponse{}, nil
}

func (r *retiringSandboxRuntime) OpenWorkspaceFile(_ context.Context, req sandboxruntime.WorkspaceFileRead) (*sandboxruntime.FileDownload, error) {
	r.fileRead = &req
	return &sandboxruntime.FileDownload{Content: io.NopCloser(bytes.NewReader(r.streamBody)), Size: int64(len(r.streamBody)), Mode: 0o600}, nil
}

func (r *retiringSandboxRuntime) ListWorkspaceFiles(context.Context, sandboxruntime.WorkspaceFileList) (*warmpool.FileListResponse, error) {
	return &warmpool.FileListResponse{}, nil
}

func (r *retiringSandboxRuntime) RetireSandboxTask(_ context.Context, workspaceID, taskID string, ttl time.Duration) error {
	r.workspaceID = workspaceID
	r.taskID = taskID
	r.ttl = ttl
	return nil
}

func TestSandboxCleanupRouteUsesWorkspaceScopedTaskIdentity(t *testing.T) {
	gin.SetMode(gin.TestMode)
	router := gin.New()
	handler := &Handler{logger: slog.Default()}
	handler.SetupRoutes(router)

	routes := make(map[string]bool)
	for _, route := range router.Routes() {
		routes[route.Method+" "+route.Path] = true
	}
	if !routes["DELETE /sandbox/task/:id"] {
		t.Fatal("task cleanup route is not registered")
	}
	if routes["DELETE /sandbox/workflow/:id"] {
		t.Fatal("workflow cleanup route must not be registered")
	}
}

func TestSandboxCleanupRequiresDedicatedBearerBeforeRuntimeAccess(t *testing.T) {
	t.Setenv(sandboxCleanupAuthSecretEnv, "cleanup-secret-for-tests")
	t.Setenv("MCP_FEATURE_WARM_POOL", "false")

	for _, test := range []struct {
		name          string
		authorization string
		wantStatus    int
	}{
		{name: "missing", wantStatus: http.StatusUnauthorized},
		{name: "wrong", authorization: "Bearer wrong-secret", wantStatus: http.StatusUnauthorized},
		{name: "activation secret", authorization: "Bearer activation-secret-for-tests", wantStatus: http.StatusUnauthorized},
		{name: "cleanup secret", authorization: "Bearer cleanup-secret-for-tests", wantStatus: http.StatusNoContent},
	} {
		t.Run(test.name, func(t *testing.T) {
			recorder := httptest.NewRecorder()
			context, _ := gin.CreateTestContext(recorder)
			context.Params = gin.Params{{Key: "id", Value: "task-123"}}
			context.Request = httptest.NewRequest(http.MethodDelete, "/sandbox/task/task-123?workspace_id=workspace-1", nil)
			if test.authorization != "" {
				context.Request.Header.Set("Authorization", test.authorization)
			}

			handler := &Handler{logger: slog.Default(), sandboxRuntime: &controlRuntimeStub{}}
			handler.deleteSandboxTask(context)
			context.Writer.WriteHeaderNow()

			if recorder.Code != test.wantStatus {
				t.Fatalf("status = %d, want %d; body=%s", recorder.Code, test.wantStatus, recorder.Body.String())
			}
		})
	}
}

func TestSandboxCleanupFailsClosedWithoutConfiguredSecret(t *testing.T) {
	t.Setenv(sandboxCleanupAuthSecretEnv, "")
	recorder := httptest.NewRecorder()
	context, _ := gin.CreateTestContext(recorder)
	context.Params = gin.Params{{Key: "id", Value: "task-123"}}
	context.Request = httptest.NewRequest(http.MethodDelete, "/sandbox/task/task-123?workspace_id=workspace-1", nil)
	context.Request.Header.Set("Authorization", "Bearer any-presented-secret")

	handler := &Handler{logger: slog.Default()}
	handler.deleteSandboxTask(context)
	context.Writer.WriteHeaderNow()

	if recorder.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want %d; body=%s", recorder.Code, http.StatusUnauthorized, recorder.Body.String())
	}
}

func TestExternalSandboxCleanupRunsEvenWhenWarmPoolFeatureIsDisabled(t *testing.T) {
	t.Setenv(sandboxCleanupAuthSecretEnv, "cleanup-secret-for-tests")
	t.Setenv("MCP_FEATURE_WARM_POOL", "false")
	t.Setenv("SANDBOX_TASK_IDLE_TTL", "42s")
	runtime := &retiringSandboxRuntime{}
	recorder := httptest.NewRecorder()
	context, _ := gin.CreateTestContext(recorder)
	context.Params = gin.Params{{Key: "id", Value: "task-123"}}
	context.Request = httptest.NewRequest(http.MethodDelete, "/sandbox/task/task-123?workspace_id=workspace-1", nil)
	context.Request.Header.Set("Authorization", "Bearer cleanup-secret-for-tests")

	handler := &Handler{logger: slog.Default(), sandboxRuntime: runtime, sandboxPolicy: SandboxPolicy{TaskIdleTTL: 42 * time.Second}}
	handler.deleteSandboxTask(context)
	context.Writer.WriteHeaderNow()

	if recorder.Code != http.StatusNoContent {
		t.Fatalf("status = %d, want 204", recorder.Code)
	}
	if runtime.workspaceID != "workspace-1" || runtime.taskID != "task-123" || runtime.ttl != 42*time.Second {
		t.Fatalf("retire = workspace %q task %q ttl %s", runtime.workspaceID, runtime.taskID, runtime.ttl)
	}
}

func TestSandboxFileRouteUsesExternalRuntimeWithoutBackend(t *testing.T) {
	t.Setenv(sandboxFileAuthSecretEnv, "file-secret-for-tests")
	runtime := &retiringSandboxRuntime{}
	handler := &Handler{logger: slog.Default(), sandboxRuntime: runtime}
	recorder := httptest.NewRecorder()
	context, _ := gin.CreateTestContext(recorder)
	context.Request = httptest.NewRequest(http.MethodPut, "/sandbox/files", strings.NewReader(`{
		"workspace_id": "workspace-1",
		"task_id": "task-1",
		"path": "input.txt",
		"content_base64": "aGVsbG8="
	}`))
	context.Request.Header.Set("Content-Type", "application/json")
	context.Request.Header.Set("Authorization", "Bearer file-secret-for-tests")

	handler.sandboxFiles(context)
	context.Writer.WriteHeaderNow()

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", recorder.Code, recorder.Body.String())
	}
	if runtime.filePut == nil {
		t.Fatalf("external runtime request = %+v", runtime.filePut)
	}
}

func TestSandboxFileReadDelegatesCompleteOnDemandUseCase(t *testing.T) {
	t.Setenv(sandboxFileAuthSecretEnv, "file-secret-for-tests")
	runtime := &retiringSandboxRuntime{}
	handler := &Handler{logger: slog.Default(), sandboxRuntime: runtime}
	recorder := httptest.NewRecorder()
	requestContext, _ := gin.CreateTestContext(recorder)
	requestContext.Request = httptest.NewRequest(
		http.MethodGet,
		"/sandbox/files?workspace_id=workspace-1&task_id=task-1&path=input.txt",
		nil,
	)
	requestContext.Request.Header.Set("Authorization", "Bearer file-secret-for-tests")

	handler.sandboxFiles(requestContext)
	requestContext.Writer.WriteHeaderNow()

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", recorder.Code, recorder.Body.String())
	}
	if runtime.fileRead == nil || !runtime.fileRead.Ensure ||
		runtime.fileRead.WorkspaceID != "workspace-1" || runtime.fileRead.TaskID != "task-1" || runtime.fileRead.Path != "input.txt" {
		t.Fatalf("workspace read use case = %+v", runtime.fileRead)
	}
}

func TestSandboxFileContentRouteStreamsBeyondInlineLimit(t *testing.T) {
	t.Setenv(sandboxFileAuthSecretEnv, "file-secret-for-tests")
	content := bytes.Repeat([]byte("q"), 16*1024*1024+1)
	digest := sha256.Sum256(content)
	runtime := &retiringSandboxRuntime{}
	handler := &Handler{logger: slog.Default(), sandboxRuntime: runtime, sandboxPolicy: SandboxPolicy{MaxFileBytes: int64(len(content))}}
	recorder := httptest.NewRecorder()
	context, _ := gin.CreateTestContext(recorder)
	requestURL := "/sandbox/file-content?workspace_id=workspace-1&task_id=task-1&path=large.bin&mode=600&size=" + strconv.Itoa(len(content)) + "&sha256=" + hex.EncodeToString(digest[:])
	context.Request = httptest.NewRequest(http.MethodPut, requestURL, bytes.NewReader(content))
	context.Request.Header.Set("Content-Type", "application/octet-stream")
	context.Request.Header.Set("Authorization", "Bearer file-secret-for-tests")

	handler.sandboxFileContent(context)
	context.Writer.WriteHeaderNow()
	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", recorder.Code, recorder.Body.String())
	}
	if runtime.streamPut == nil || runtime.streamPut.Mode != 0o600 || !bytes.Equal(runtime.streamBody, content) {
		t.Fatalf("streamed runtime request = %+v bytes=%d", runtime.streamPut, len(runtime.streamBody))
	}
}

func TestSandboxFileRouteRejectsMissingBearerBeforeBackendAccess(t *testing.T) {
	t.Setenv(sandboxFileAuthSecretEnv, "file-secret-for-tests")
	runtime := &retiringSandboxRuntime{}
	handler := &Handler{logger: slog.Default(), sandboxRuntime: runtime}
	recorder := httptest.NewRecorder()
	context, _ := gin.CreateTestContext(recorder)
	context.Request = httptest.NewRequest(http.MethodPut, "/sandbox/files", strings.NewReader(`{
		"workspace_id": "workspace-1",
		"task_id": "task-1",
		"path": "input.txt",
		"content_base64": "aGVsbG8="
	}`))
	context.Request.Header.Set("Content-Type", "application/json")

	handler.sandboxFiles(context)
	context.Writer.WriteHeaderNow()

	if recorder.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want 401; body=%s", recorder.Code, recorder.Body.String())
	}
	if runtime.filePut != nil {
		t.Fatal("sandbox runtime was accessed before authorization")
	}
}

func TestSandboxArtifactRoutesRequireFileBearer(t *testing.T) {
	t.Setenv(sandboxFileAuthSecretEnv, "file-secret-for-tests")
	handler := &Handler{logger: slog.Default()}

	for _, test := range []struct {
		name          string
		authorization string
		wantStatus    int
	}{
		{name: "missing", wantStatus: http.StatusUnauthorized},
		{name: "wrong", authorization: "Bearer wrong", wantStatus: http.StatusUnauthorized},
		{name: "valid", authorization: "Bearer file-secret-for-tests", wantStatus: http.StatusServiceUnavailable},
	} {
		t.Run(test.name, func(t *testing.T) {
			recorder := httptest.NewRecorder()
			context, _ := gin.CreateTestContext(recorder)
			context.Request = httptest.NewRequest(http.MethodGet, "/sandbox/artifacts?workspace_id=workspace-1&task_id=task-1", nil)
			context.Request.Header.Set("Authorization", test.authorization)

			handler.sandboxArtifactsCollection(context)
			context.Writer.WriteHeaderNow()

			if recorder.Code != test.wantStatus {
				t.Fatalf("status = %d, want %d; body=%s", recorder.Code, test.wantStatus, recorder.Body.String())
			}
		})
	}
}

func TestSandboxArtifactPublicationUsesWorkspaceReadUseCase(t *testing.T) {
	t.Setenv(sandboxFileAuthSecretEnv, "file-secret-for-tests")
	runtime := &retiringSandboxRuntime{streamBody: []byte("published artifact")}
	store := &recordingArtifactStore{}
	handler := &Handler{logger: slog.Default(), sandboxRuntime: runtime, sandboxArtifacts: store}
	recorder := httptest.NewRecorder()
	requestContext, _ := gin.CreateTestContext(recorder)
	requestContext.Request = httptest.NewRequest(
		http.MethodPost,
		"/sandbox/artifacts",
		strings.NewReader(`{"workspace_id":"workspace-1","task_id":"task-1","path":"result.txt","content_type":"text/plain"}`),
	)
	requestContext.Request.Header.Set("Content-Type", "application/json")
	requestContext.Request.Header.Set("Authorization", "Bearer file-secret-for-tests")

	handler.sandboxArtifactsCollection(requestContext)
	requestContext.Writer.WriteHeaderNow()

	if recorder.Code != http.StatusCreated {
		t.Fatalf("status = %d, want 201; body=%s", recorder.Code, recorder.Body.String())
	}
	if runtime.fileRead == nil || runtime.fileRead.Ensure || runtime.fileRead.WorkspaceID != "workspace-1" ||
		runtime.fileRead.TaskID != "task-1" || runtime.fileRead.Path != "result.txt" {
		t.Fatalf("artifact workspace read = %+v", runtime.fileRead)
	}
	if string(store.published) != "published artifact" {
		t.Fatalf("published content = %q", store.published)
	}
}

func TestSandboxArtifactDownloadVerifiesBeforeCommittingResponse(t *testing.T) {
	t.Setenv(sandboxFileAuthSecretEnv, "file-secret-for-tests")
	corrupt := []byte("corrupt artifact")
	store := &recordingArtifactStore{
		artifact: artifactstore.Artifact{
			ID: "art_0123456789abcdef0123456789abcdef", Name: "result.txt",
			Size: int64(len(corrupt)), ContentType: "text/plain",
		},
		openBody: &eofFailureReadCloser{
			reader: bytes.NewReader(corrupt),
			err:    errors.New("artifact checksum verification failed"),
		},
	}
	handler := &Handler{logger: slog.Default(), sandboxArtifacts: store}
	recorder := httptest.NewRecorder()
	requestContext, _ := gin.CreateTestContext(recorder)
	requestContext.Params = gin.Params{{Key: "id", Value: store.artifact.ID}}
	requestContext.Request = httptest.NewRequest(
		http.MethodGet,
		"/sandbox/artifacts/"+store.artifact.ID+"?workspace_id=workspace-1&task_id=task-1",
		nil,
	)
	requestContext.Request.Header.Set("Authorization", "Bearer file-secret-for-tests")

	handler.getSandboxArtifact(requestContext)
	requestContext.Writer.WriteHeaderNow()

	if recorder.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want 502; body=%s", recorder.Code, recorder.Body.String())
	}
	if strings.Contains(recorder.Body.String(), string(corrupt)) {
		t.Fatalf("corrupt artifact bytes were exposed: %q", recorder.Body.String())
	}
	if disposition := recorder.Header().Get("Content-Disposition"); disposition != "" {
		t.Fatalf("content disposition committed before verification: %q", disposition)
	}
}
