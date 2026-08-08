package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/activationauth"
)

func signFiles(t *testing.T, body []byte, workspaceID, taskID string) string {
	t.Helper()
	token, err := activationauth.SignFromEnv(activationauth.ScopeFiles, activationauth.Identity{
		WorkspaceID: workspaceID, TaskID: taskID, Generation: 0, FencingToken: 1,
	}, activationauth.BodySHA256(body), time.Now())
	if err != nil {
		t.Fatalf("sign files request: %v", err)
	}
	return token
}

func signCleanup(t *testing.T, workspaceID, taskID string) string {
	t.Helper()
	token, err := activationauth.SignFromEnv(activationauth.ScopeCleanup, activationauth.Identity{
		WorkspaceID: workspaceID, TaskID: taskID, Generation: 0, FencingToken: 1,
	}, activationauth.BodySHA256(nil), time.Now())
	if err != nil {
		t.Fatalf("sign cleanup request: %v", err)
	}
	return token
}

func deleteTaskWorkspace(t *testing.T, workspaceID, taskID, tokenWorkspaceID string) *httptest.ResponseRecorder {
	t.Helper()
	query := url.Values{}
	query.Set("workspace_id", workspaceID)
	query.Set("task_id", taskID)
	r := httptest.NewRequest(http.MethodDelete, "/workspace/task?"+query.Encode(), nil)
	r.Header.Set("Authorization", "Bearer "+signCleanup(t, tokenWorkspaceID, taskID))
	w := httptest.NewRecorder()
	workspaceTaskHandler(w, r)
	return w
}

func putFile(t *testing.T, workspaceID, taskID, path string, content []byte) *httptest.ResponseRecorder {
	t.Helper()
	body, err := json.Marshal(FilesPutRequest{
		WorkspaceID:   workspaceID,
		TaskID:        taskID,
		Path:          path,
		ContentBase64: base64.StdEncoding.EncodeToString(content),
	})
	if err != nil {
		t.Fatalf("marshal put request: %v", err)
	}
	r := httptest.NewRequest(http.MethodPut, "/files", bytes.NewReader(body))
	r.Header.Set("Authorization", "Bearer "+signFiles(t, body, workspaceID, taskID))
	w := httptest.NewRecorder()
	filesHandler(w, r)
	return w
}

func getFile(t *testing.T, workspaceID, taskID, path string) *httptest.ResponseRecorder {
	t.Helper()
	query := url.Values{}
	query.Set("workspace_id", workspaceID)
	query.Set("task_id", taskID)
	query.Set("path", path)
	r := httptest.NewRequest(http.MethodGet, "/files?"+query.Encode(), nil)
	binding := activationauth.TransferSHA256(http.MethodGet, "file:"+path, -1, 0, activationauth.BodySHA256(nil))
	token, err := activationauth.SignFromEnv(activationauth.ScopeFiles, activationauth.Identity{
		WorkspaceID: workspaceID, TaskID: taskID, Generation: 0, FencingToken: 1,
	}, binding, time.Now())
	if err != nil {
		t.Fatalf("sign file get: %v", err)
	}
	r.Header.Set("Authorization", "Bearer "+token)
	w := httptest.NewRecorder()
	filesHandler(w, r)
	return w
}

func listFiles(t *testing.T, workspaceID, taskID, prefix string) *httptest.ResponseRecorder {
	t.Helper()
	query := url.Values{}
	query.Set("workspace_id", workspaceID)
	query.Set("task_id", taskID)
	query.Set("list", prefix)
	r := httptest.NewRequest(http.MethodGet, "/files?"+query.Encode(), nil)
	binding := activationauth.TransferSHA256(http.MethodGet, "list:"+prefix, -1, 0, activationauth.BodySHA256(nil))
	token, err := activationauth.SignFromEnv(activationauth.ScopeFiles, activationauth.Identity{
		WorkspaceID: workspaceID, TaskID: taskID, Generation: 0, FencingToken: 1,
	}, binding, time.Now())
	if err != nil {
		t.Fatalf("sign file list: %v", err)
	}
	r.Header.Set("Authorization", "Bearer "+token)
	w := httptest.NewRecorder()
	filesHandler(w, r)
	return w
}

func putFileStream(t *testing.T, workspaceID, taskID, path string, content []byte) *httptest.ResponseRecorder {
	t.Helper()
	digest := sha256.Sum256(content)
	sha := hex.EncodeToString(digest[:])
	query := url.Values{}
	query.Set("workspace_id", workspaceID)
	query.Set("task_id", taskID)
	query.Set("path", path)
	query.Set("size", strconv.Itoa(len(content)))
	query.Set("sha256", sha)
	query.Set("mode", "600")
	r := httptest.NewRequest(http.MethodPut, "/files/content?"+query.Encode(), bytes.NewReader(content))
	transferDigest := activationauth.TransferSHA256(http.MethodPut, path, int64(len(content)), 0o600, sha)
	token, err := activationauth.SignFromEnv(activationauth.ScopeFiles, activationauth.Identity{
		WorkspaceID: workspaceID, TaskID: taskID, Generation: 0, FencingToken: 1,
	}, transferDigest, time.Now())
	if err != nil {
		t.Fatalf("sign streamed put: %v", err)
	}
	r.Header.Set("Authorization", "Bearer "+token)
	w := httptest.NewRecorder()
	fileContentHandler(w, r)
	return w
}

func TestFileContentPutRejectsDifferentExecutorIncarnationBeforeWorkspaceAccess(t *testing.T) {
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))
	originalRoot := workspaceRoot
	workspaceRoot = t.TempDir()
	t.Cleanup(func() { workspaceRoot = originalRoot })
	const expectedIncarnation = "00000000-0000-4000-8000-000000000001"
	content := []byte("x")
	digest := sha256.Sum256(content)
	sha := hex.EncodeToString(digest[:])
	query := url.Values{}
	query.Set("workspace_id", "workspace-incarnation")
	query.Set("task_id", "task-incarnation")
	query.Set("executor_incarnation", expectedIncarnation)
	query.Set("path", "input.txt")
	query.Set("size", "1")
	query.Set("sha256", sha)
	query.Set("mode", "600")
	request := httptest.NewRequest(http.MethodPut, "/files/content?"+query.Encode(), bytes.NewReader(content))
	request.ContentLength = 1
	binding := activationauth.BoundTransferSHA256(http.MethodPut, "input.txt", 1, 0o600, sha, expectedIncarnation)
	token, err := activationauth.SignFromEnv(activationauth.ScopeFiles, activationauth.Identity{
		WorkspaceID: "workspace-incarnation", TaskID: "task-incarnation", Generation: 0, FencingToken: 1,
	}, binding, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("Authorization", "Bearer "+token)
	response := httptest.NewRecorder()
	fileContentHandler(response, request)
	if response.Code != http.StatusPreconditionFailed || !strings.Contains(response.Body.String(), "executor_incarnation_changed") {
		t.Fatalf("response = %d %s, want executor incarnation precondition", response.Code, response.Body.String())
	}
	if _, err := os.Stat(filepath.Join(workspaceRoot, "workspace-incarnation", "task-incarnation")); !os.IsNotExist(err) {
		t.Fatalf("replacement executor touched workspace before rejecting file: %v", err)
	}
}

func getFileStream(t *testing.T, workspaceID, taskID, path string) *httptest.ResponseRecorder {
	t.Helper()
	query := url.Values{}
	query.Set("workspace_id", workspaceID)
	query.Set("task_id", taskID)
	query.Set("path", path)
	r := httptest.NewRequest(http.MethodGet, "/files/content?"+query.Encode(), nil)
	transferDigest := activationauth.TransferSHA256(http.MethodGet, path, -1, 0, activationauth.BodySHA256(nil))
	token, err := activationauth.SignFromEnv(activationauth.ScopeFiles, activationauth.Identity{
		WorkspaceID: workspaceID, TaskID: taskID, Generation: 0, FencingToken: 1,
	}, transferDigest, time.Now())
	if err != nil {
		t.Fatalf("sign streamed get: %v", err)
	}
	r.Header.Set("Authorization", "Bearer "+token)
	w := httptest.NewRecorder()
	fileContentHandler(w, r)
	return w
}

func TestFilesHandlerWriteReadRoundTrip(t *testing.T) {
	workspaceRoot = t.TempDir()
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))

	if w := putFile(t, "ws", "task-files", "src/nested/a.py", []byte("print('ok')")); w.Code != http.StatusOK {
		t.Fatalf("put returned %d: %s", w.Code, w.Body.String())
	}

	w := getFile(t, "ws", "task-files", "src/nested/a.py")
	if w.Code != http.StatusOK {
		t.Fatalf("get returned %d: %s", w.Code, w.Body.String())
	}
	var resp FilesGetResponse
	if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
		t.Fatalf("decode get response: %v", err)
	}
	decoded, err := base64.StdEncoding.DecodeString(resp.ContentBase64)
	if err != nil {
		t.Fatalf("decode content: %v", err)
	}
	if string(decoded) != "print('ok')" {
		t.Fatalf("round-trip content = %q", string(decoded))
	}
	if resp.Size != int64(len("print('ok')")) {
		t.Fatalf("round-trip size = %d", resp.Size)
	}
}

func TestFileContentHandlerStreamsBeyondInlineLimit(t *testing.T) {
	workspaceRoot = t.TempDir()
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))
	content := bytes.Repeat([]byte("z"), maxFileContentBytes+1)
	if w := putFileStream(t, "ws", "task-stream", "inputs/large.bin", content); w.Code != http.StatusOK {
		t.Fatalf("stream put returned %d: %s", w.Code, w.Body.String())
	}
	w := getFileStream(t, "ws", "task-stream", "inputs/large.bin")
	if w.Code != http.StatusOK {
		t.Fatalf("stream get returned %d: %s", w.Code, w.Body.String())
	}
	if !bytes.Equal(w.Body.Bytes(), content) {
		t.Fatalf("streamed round trip returned %d bytes, want %d", w.Body.Len(), len(content))
	}
}

func TestFileContentTokenCannotBeReplayedForAnotherPath(t *testing.T) {
	workspaceRoot = t.TempDir()
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))
	content := []byte("secret")
	digest := sha256.Sum256(content)
	sha := hex.EncodeToString(digest[:])
	query := url.Values{
		"workspace_id": {"ws"}, "task_id": {"task-replay"}, "path": {"inputs/b.txt"},
		"size": {strconv.Itoa(len(content))}, "sha256": {sha}, "mode": {"600"},
	}
	request := httptest.NewRequest(http.MethodPut, "/files/content?"+query.Encode(), bytes.NewReader(content))
	token, err := activationauth.SignFromEnv(activationauth.ScopeFiles, activationauth.Identity{
		WorkspaceID: "ws", TaskID: "task-replay", FencingToken: 1,
	}, activationauth.TransferSHA256(http.MethodPut, "inputs/a.txt", int64(len(content)), 0o600, sha), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("Authorization", "Bearer "+token)
	response := httptest.NewRecorder()
	fileContentHandler(response, request)
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("replayed token status = %d, want 401", response.Code)
	}
}

func TestFilesHandlerSharesFilesystemWithExecute(t *testing.T) {
	workspaceRoot = t.TempDir()
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))

	if w := putFile(t, "workspace-test", "task-shared", "hello.txt", []byte("from-file-api")); w.Code != http.StatusOK {
		t.Fatalf("put returned %d: %s", w.Code, w.Body.String())
	}
	// A bash command in the same task must see the file the file API wrote.
	resp := postExecute(t, ExecuteRequest{TaskID: "task-shared", WorkspaceID: "workspace-test"}, "cat hello.txt")
	if resp.ExitCode != 0 || !strings.Contains(resp.Stdout, "from-file-api") {
		t.Fatalf("bash did not see file-API write: exit=%d stdout=%q stderr=%q", resp.ExitCode, resp.Stdout, resp.Stderr)
	}
}

func TestFilesHandlerDoesNotShareFilesAcrossTasks(t *testing.T) {
	workspaceRoot = t.TempDir()
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))

	if w := putFile(t, "workspace-test", "task-a", "private.txt", []byte("task-a-only")); w.Code != http.StatusOK {
		t.Fatalf("put returned %d: %s", w.Code, w.Body.String())
	}
	if w := getFile(t, "workspace-test", "task-b", "private.txt"); w.Code != http.StatusGone {
		t.Fatalf("task-b observed task-a file: status=%d body=%s", w.Code, w.Body.String())
	}
}

func TestFilesHandlerDoesNotShareFilesAcrossWorkspaces(t *testing.T) {
	workspaceRoot = t.TempDir()
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))

	if w := putFile(t, "workspace-a", "same-task", "private.txt", []byte("workspace-a-only")); w.Code != http.StatusOK {
		t.Fatalf("put returned %d: %s", w.Code, w.Body.String())
	}
	if w := getFile(t, "workspace-b", "same-task", "private.txt"); w.Code != http.StatusGone {
		t.Fatalf("workspace-b observed workspace-a file: status=%d body=%s", w.Code, w.Body.String())
	}
}

func TestWorkspaceTaskDeleteRemovesOnlyExactWorkspaceAndTask(t *testing.T) {
	workspaceRoot = t.TempDir()
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))

	for _, workspaceID := range []string{"workspace-a", "workspace-b"} {
		if w := putFile(t, workspaceID, "same-task", "private.txt", []byte(workspaceID)); w.Code != http.StatusOK {
			t.Fatalf("put for %s returned %d: %s", workspaceID, w.Code, w.Body.String())
		}
	}
	if w := deleteTaskWorkspace(t, "workspace-a", "same-task", "workspace-a"); w.Code != http.StatusNoContent {
		t.Fatalf("delete returned %d: %s", w.Code, w.Body.String())
	}
	if w := getFile(t, "workspace-a", "same-task", "private.txt"); w.Code != http.StatusGone {
		t.Fatalf("deleted workspace file returned %d: %s", w.Code, w.Body.String())
	}
	if w := getFile(t, "workspace-b", "same-task", "private.txt"); w.Code != http.StatusOK {
		t.Fatalf("sibling workspace was deleted: %d: %s", w.Code, w.Body.String())
	}
	// Deletion is idempotent so cleanup activity retries are safe.
	if w := deleteTaskWorkspace(t, "workspace-a", "same-task", "workspace-a"); w.Code != http.StatusNoContent {
		t.Fatalf("idempotent delete returned %d: %s", w.Code, w.Body.String())
	}
}

func TestWorkspaceTaskDeleteRejectsCrossWorkspaceToken(t *testing.T) {
	workspaceRoot = t.TempDir()
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))
	if w := putFile(t, "workspace-a", "task-a", "private.txt", []byte("keep")); w.Code != http.StatusOK {
		t.Fatalf("put returned %d: %s", w.Code, w.Body.String())
	}

	if w := deleteTaskWorkspace(t, "workspace-a", "task-a", "workspace-b"); w.Code != http.StatusUnauthorized {
		t.Fatalf("cross-workspace cleanup returned %d: %s", w.Code, w.Body.String())
	}
	if w := getFile(t, "workspace-a", "task-a", "private.txt"); w.Code != http.StatusOK {
		t.Fatalf("unauthorized cleanup deleted file: %d: %s", w.Code, w.Body.String())
	}
}

func TestFilesHandlerListReturnsWrittenPaths(t *testing.T) {
	workspaceRoot = t.TempDir()
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))

	for _, path := range []string{"a.txt", "reports/b.txt", "reports/c.txt"} {
		if w := putFile(t, "ws", "task-list", path, []byte("x")); w.Code != http.StatusOK {
			t.Fatalf("put %s returned %d: %s", path, w.Code, w.Body.String())
		}
	}

	w := listFiles(t, "ws", "task-list", "reports")
	if w.Code != http.StatusOK {
		t.Fatalf("list returned %d: %s", w.Code, w.Body.String())
	}
	var resp FilesListResponse
	if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
		t.Fatalf("decode list response: %v", err)
	}
	got := strings.Join(resp.Paths, ",")
	if got != "reports/b.txt,reports/c.txt" {
		t.Fatalf("prefix-scoped list = %q", got)
	}
}

func TestFilesHandlerRejectsPathTraversal(t *testing.T) {
	workspaceRoot = t.TempDir()
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))

	for _, path := range []string{"../escape.txt", "/etc/passwd", "a/../../escape.txt"} {
		w := putFile(t, "ws", "task-traversal", path, []byte("x"))
		if w.Code != http.StatusBadRequest {
			t.Fatalf("traversal path %q accepted with %d: %s", path, w.Code, w.Body.String())
		}
	}
}

func TestFilesHandlerGetMissingFileReturns404(t *testing.T) {
	workspaceRoot = t.TempDir()
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))
	if w := putFile(t, "ws", "task-missing", "existing.txt", []byte("x")); w.Code != http.StatusOK {
		t.Fatalf("put returned %d: %s", w.Code, w.Body.String())
	}

	w := getFile(t, "ws", "task-missing", "nope.txt")
	if w.Code != http.StatusNotFound {
		t.Fatalf("missing file returned %d: %s", w.Code, w.Body.String())
	}
}

func TestFilesHandlerRejectsMissingBearer(t *testing.T) {
	workspaceRoot = t.TempDir()
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))

	body, _ := json.Marshal(FilesPutRequest{
		WorkspaceID: "ws", TaskID: "task-unauth", Path: "a.txt", ContentBase64: base64.StdEncoding.EncodeToString([]byte("x")),
	})
	r := httptest.NewRequest(http.MethodPut, "/files", bytes.NewReader(body))
	w := httptest.NewRecorder()
	filesHandler(w, r)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("missing bearer returned %d: %s", w.Code, w.Body.String())
	}
}

func TestFilesHandlerRejectsTokenForDifferentTask(t *testing.T) {
	workspaceRoot = t.TempDir()
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))

	body, _ := json.Marshal(FilesPutRequest{
		WorkspaceID: "ws", TaskID: "task-real", Path: "a.txt", ContentBase64: base64.StdEncoding.EncodeToString([]byte("x")),
	})
	// Token minted for a different task must not authorize this write.
	r := httptest.NewRequest(http.MethodPut, "/files", bytes.NewReader(body))
	r.Header.Set("Authorization", "Bearer "+signFiles(t, body, "ws", "task-other"))
	w := httptest.NewRecorder()
	filesHandler(w, r)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("cross-task token returned %d: %s", w.Code, w.Body.String())
	}
}
