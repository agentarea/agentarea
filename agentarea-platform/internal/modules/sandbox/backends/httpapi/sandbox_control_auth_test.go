package httpapi

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	redis "github.com/redis/go-redis/v9"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/sandboxcontrol"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/sandboxcontrolauth"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/warmpool"
)

func TestSandboxControlRoutesRequireWorkspaceScopedAuthorization(t *testing.T) {
	secret := strings.Repeat("c", 48)
	server := miniredis.RunT(t)
	policy := sandboxcontrol.ExecutionPolicy{
		DefaultTimeoutSeconds: 120, MaxTimeoutSeconds: 1800,
		QueueTimeout: 5 * time.Minute, CompletionGrace: 2 * time.Minute,
	}
	store, err := sandboxcontrol.NewRedisStore(
		redis.NewClient(&redis.Options{Addr: server.Addr()}), "api-auth", time.Hour, policy,
		sandboxcontrol.WithEventStreams("auth.requests", "auth.events", "test"),
	)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = store.RedisClient().Close() }()
	service, err := sandboxcontrol.NewService(store, policy)
	if err != nil {
		t.Fatal(err)
	}
	handler := &Handler{secrets: Secrets{Control: secret}, sandboxControl: service, logger: slog.New(slog.NewTextHandler(io.Discard, nil))}
	router := http.NewServeMux()
	router.HandleFunc("POST /sandbox/executions", serve(handler.createSandboxExecution))
	router.HandleFunc("GET /sandbox/executions/{id}", serve(handler.getSandboxExecution))
	router.HandleFunc("DELETE /sandbox/executions/{id}", serve(handler.cancelSandboxExecution))

	body, err := json.Marshal(sandboxcontrol.ExecutionCreateRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1",
		Command: warmpool.ExecuteRequest{CommandBody: "echo ok"},
	})
	if err != nil {
		t.Fatal(err)
	}
	unauthorized := performSandboxControlRequest(router, http.MethodPost, "/sandbox/executions", body, nil)
	if unauthorized.Code != http.StatusUnauthorized {
		t.Fatalf("unauthorized create status = %d, body=%s", unauthorized.Code, unauthorized.Body.String())
	}
	requests, err := server.Stream("auth.requests")
	if err == nil || !strings.Contains(err.Error(), "no such key") {
		if err != nil {
			t.Fatalf("inspect unauthorized request stream: %v", err)
		}
		if len(requests) != 0 {
			t.Fatalf("unauthorized create published %d requests", len(requests))
		}
	}

	createIdentity := sandboxcontrolauth.Identity{WorkspaceID: "workspace-1", TaskID: "task-1"}
	createToken, err := sandboxcontrolauth.Sign(
		[]byte(secret), sandboxcontrolauth.ScopeCreate, createIdentity,
		sandboxcontrolauth.BodySHA256(body), time.Now().UTC(), time.Minute, "0123456789abcdef",
	)
	if err != nil {
		t.Fatal(err)
	}
	created := performSandboxControlRequest(router, http.MethodPost, "/sandbox/executions", body, map[string]string{
		"Authorization": "Bearer " + createToken,
	})
	if created.Code != http.StatusAccepted {
		t.Fatalf("authorized create status = %d, body=%s", created.Code, created.Body.String())
	}
	var record sandboxcontrol.ExecutionRecord
	if err := json.Unmarshal(created.Body.Bytes(), &record); err != nil {
		t.Fatal(err)
	}
	if record.Command.TimeoutSeconds != 120 || record.Revision != 1 {
		t.Fatalf("created record policy/revision = %#v", record)
	}

	wrongIdentity := sandboxcontrolauth.Identity{WorkspaceID: "workspace-2", TaskID: "task-1", ExecutionID: record.ID}
	wrongToken, err := sandboxcontrolauth.Sign(
		[]byte(secret), sandboxcontrolauth.ScopeRead, wrongIdentity,
		sandboxcontrolauth.BodySHA256(nil), time.Now().UTC(), time.Minute, "fedcba9876543210",
	)
	if err != nil {
		t.Fatal(err)
	}
	wrongScope := performSandboxControlRequest(router, http.MethodGet, "/sandbox/executions/"+record.ID, nil, map[string]string{
		"Authorization":        "Bearer " + wrongToken,
		sandboxWorkspaceHeader: "workspace-2", sandboxTaskHeader: "task-1",
	})
	if wrongScope.Code != http.StatusForbidden {
		t.Fatalf("wrong workspace status = %d, body=%s", wrongScope.Code, wrongScope.Body.String())
	}

	cancelIdentity := sandboxcontrolauth.Identity{WorkspaceID: "workspace-1", TaskID: "task-1", ExecutionID: record.ID}
	cancelToken, err := sandboxcontrolauth.Sign(
		[]byte(secret), sandboxcontrolauth.ScopeCancel, cancelIdentity,
		sandboxcontrolauth.BodySHA256(nil), time.Now().UTC(), time.Minute, "abcdef0123456789",
	)
	if err != nil {
		t.Fatal(err)
	}
	cancelled := performSandboxControlRequest(router, http.MethodDelete, "/sandbox/executions/"+record.ID, nil, map[string]string{
		"Authorization":        "Bearer " + cancelToken,
		sandboxWorkspaceHeader: "workspace-1", sandboxTaskHeader: "task-1",
	})
	if cancelled.Code != http.StatusOK {
		t.Fatalf("cancel status = %d, body=%s", cancelled.Code, cancelled.Body.String())
	}
	stored, err := service.GetExecution(context.Background(), record.ID)
	if err != nil || stored.Status != sandboxcontrol.ExecutionStatusCancelled {
		t.Fatalf("cancelled aggregate = %#v, error=%v", stored, err)
	}
}

func performSandboxControlRequest(router http.Handler, method, path string, body []byte, headers map[string]string) *httptest.ResponseRecorder {
	request := httptest.NewRequest(method, path, bytes.NewReader(body))
	if body != nil {
		request.Header.Set("Content-Type", "application/json")
	}
	for key, value := range headers {
		request.Header.Set(key, value)
	}
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)
	return recorder
}
