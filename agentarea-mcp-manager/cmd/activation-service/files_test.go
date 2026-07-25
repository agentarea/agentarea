package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
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
	r.Header.Set("Authorization", "Bearer "+signFiles(t, nil, workspaceID, taskID))
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
	r.Header.Set("Authorization", "Bearer "+signFiles(t, nil, workspaceID, taskID))
	w := httptest.NewRecorder()
	filesHandler(w, r)
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
