package warmpool

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/activationauth"
	"github.com/agentarea/mcp-manager/internal/workspace"
)

func TestPostExecuteUsesTaskBoundBearerToken(t *testing.T) {
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))
	digest := strings.Repeat("a", 64)
	ref := &workspace.ManifestRef{
		SchemaVersion: workspace.SchemaVersion, WorkspaceID: "workspace-1", TaskID: "task-1",
		Generation: 2, BaseGeneration: 1, FencingToken: 7,
		ManifestURI:    "s3://bucket/workspaces/workspace-1/tasks/task-1/manifests/2-" + digest + ".json",
		ManifestSHA256: digest,
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, readErr := io.ReadAll(r.Body)
		if readErr != nil {
			t.Errorf("read body: %v", readErr)
		}
		token, err := activationauth.BearerToken(r.Header.Get("Authorization"))
		if err != nil {
			t.Errorf("BearerToken() error = %v", err)
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		err = activationauth.VerifyFromEnv(token, activationauth.ScopeExecute, activationauth.Identity{
			WorkspaceID: "workspace-1", TaskID: "task-1", Generation: 0, FencingToken: 1,
		}, activationauth.BodySHA256(body), time.Now())
		if err != nil {
			t.Errorf("VerifyFromEnv() error = %v", err)
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		_ = json.NewEncoder(w).Encode(ExecuteResponse{ExitCode: 0})
	}))
	defer server.Close()

	_, err := PostExecute(context.Background(), server.URL, ExecuteRequest{
		CommandBody: "echo ok", WorkspaceID: "workspace-1", TaskID: "task-1",
		WorkspaceManifestRef: ref,
	}, time.Second)
	if err != nil {
		t.Fatal(err)
	}
}

func TestPostWritebackUsesSeparateScope(t *testing.T) {
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, readErr := io.ReadAll(r.Body)
		if readErr != nil {
			t.Errorf("read body: %v", readErr)
		}
		token, err := activationauth.BearerToken(r.Header.Get("Authorization"))
		if err != nil {
			t.Errorf("BearerToken() error = %v", err)
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		err = activationauth.VerifyFromEnv(token, activationauth.ScopeWriteback, activationauth.Identity{
			WorkspaceID: "workspace-1", TaskID: "task-1", Generation: 2, FencingToken: 7,
		}, activationauth.BodySHA256(body), time.Now())
		if err != nil {
			t.Errorf("VerifyFromEnv() error = %v", err)
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		_ = json.NewEncoder(w).Encode(workspace.WritebackResponse{})
	}))
	defer server.Close()

	_, err := PostWriteback(context.Background(), server.URL, workspace.WritebackRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", BaseGeneration: 2, FencingToken: 7,
	}, time.Second)
	if err != nil {
		t.Fatal(err)
	}
}

func TestPostExecuteFailsClosedWithoutAuthSecret(t *testing.T) {
	t.Setenv(activationauth.SecretEnv, "")
	ref := &workspace.ManifestRef{WorkspaceID: "workspace-1", TaskID: "task-1", Generation: 1, FencingToken: 1}
	_, err := PostExecute(context.Background(), "http://127.0.0.1:1", ExecuteRequest{
		CommandBody: "echo ok", WorkspaceID: "workspace-1", TaskID: "task-1",
		WorkspaceManifestRef: ref,
	}, time.Second)
	if err == nil || !strings.Contains(err.Error(), activationauth.SecretEnv) {
		t.Fatalf("PostExecute() error = %v, want missing secret", err)
	}
}

func TestDeleteTaskWorkspaceUsesSeparateTaskBoundScope(t *testing.T) {
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodDelete || r.URL.Path != "/workspace/task" ||
			r.URL.Query().Get("workspace_id") != "workspace-1" || r.URL.Query().Get("task_id") != "task-1" {
			t.Errorf("unexpected cleanup request: %s %s", r.Method, r.URL.String())
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		token, err := activationauth.BearerToken(r.Header.Get("Authorization"))
		if err != nil {
			t.Errorf("BearerToken() error = %v", err)
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		err = activationauth.VerifyFromEnv(token, activationauth.ScopeCleanup, activationauth.Identity{
			WorkspaceID: "workspace-1", TaskID: "task-1", Generation: 0, FencingToken: 1,
		}, activationauth.BodySHA256(nil), time.Now())
		if err != nil {
			t.Errorf("VerifyFromEnv() error = %v", err)
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()

	if err := DeleteTaskWorkspace(context.Background(), server.URL, "workspace-1", "task-1", time.Second); err != nil {
		t.Fatal(err)
	}
}

func TestFileReadMapsReclaimedWorkspaceToTypedGone(t *testing.T) {
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "gone", http.StatusGone)
	}))
	defer server.Close()

	if _, err := GetFile(context.Background(), server.URL, "workspace-1", "task-1", "report.txt", time.Second); !errors.Is(err, ErrTaskWorkspaceGone) {
		t.Fatalf("GetFile() error = %v, want ErrTaskWorkspaceGone", err)
	}
	if _, err := ListFiles(context.Background(), server.URL, "workspace-1", "task-1", "", time.Second); !errors.Is(err, ErrTaskWorkspaceGone) {
		t.Fatalf("ListFiles() error = %v, want ErrTaskWorkspaceGone", err)
	}
}

func TestPutFileStreamSignsAndTransfersRawContent(t *testing.T) {
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))
	content := bytes.Repeat([]byte("x"), 1024*1024+7)
	digest := sha256.Sum256(content)
	digestHex := hex.EncodeToString(digest[:])
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPut || r.URL.Path != "/files/content" || r.URL.Query().Get("path") != "inputs/data.bin" {
			t.Errorf("unexpected request: %s %s", r.Method, r.URL.String())
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		token, err := activationauth.BearerToken(r.Header.Get("Authorization"))
		if err != nil {
			t.Errorf("BearerToken() error = %v", err)
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		if err := activationauth.VerifyFromEnv(token, activationauth.ScopeFiles, activationauth.Identity{
			WorkspaceID: "workspace-1", TaskID: "task-1", Generation: 0, FencingToken: 1,
		}, activationauth.TransferSHA256(http.MethodPut, "inputs/data.bin", int64(len(content)), 0o600, digestHex), time.Now()); err != nil {
			t.Errorf("VerifyFromEnv() error = %v", err)
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		body, _ := io.ReadAll(r.Body)
		if !bytes.Equal(body, content) {
			t.Errorf("body bytes = %d, want %d", len(body), len(content))
		}
		_ = json.NewEncoder(w).Encode(FilePutResponse{Path: "inputs/data.bin", Size: int64(len(body))})
	}))
	defer server.Close()

	result, err := PutFileStream(context.Background(), server.URL, FileTransferRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", Path: "inputs/data.bin",
		Size: int64(len(content)), SHA256: digestHex,
		Mode: 0o600,
	}, bytes.NewReader(content), time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if result.Size != int64(len(content)) {
		t.Fatalf("uploaded size = %d", result.Size)
	}
}
