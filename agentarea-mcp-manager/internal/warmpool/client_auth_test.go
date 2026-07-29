package warmpool

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/activationauth"
	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
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
		PackageInstall: runtimeinfo.PackageInstallAllowed,
		CommandBody:    "echo ok", WorkspaceID: "workspace-1", TaskID: "task-1",
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
		PackageInstall: runtimeinfo.PackageInstallAllowed,
		CommandBody:    "echo ok", WorkspaceID: "workspace-1", TaskID: "task-1",
		WorkspaceManifestRef: ref,
	}, time.Second)
	if err == nil || !strings.Contains(err.Error(), activationauth.SecretEnv) {
		t.Fatalf("PostExecute() error = %v, want missing secret", err)
	}
}
