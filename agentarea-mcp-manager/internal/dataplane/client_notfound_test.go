package dataplane

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/agentarea/mcp-manager/internal/backends"
)

func testClient(t *testing.T, handler http.HandlerFunc) *Client {
	t.Helper()
	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)
	return NewClient(&ClientConfig{BaseURL: server.URL, Token: "0123456789012345678901234567890123456789"})
}

// The demand gateway decides to create a workload from exactly one signal:
// backends.ErrInstanceNotFound. While a 404 arrived as an untyped string, a new
// instance never got created -- EnsureReady stopped at "inspect MCP runtime
// status" and the caller saw 502.
func TestGetInstanceStatusReportsMissingInstanceAsNotFound(t *testing.T) {
	client := testClient(t, func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, `{"error":"unknown instance"}`, http.StatusNotFound)
	})

	_, err := client.GetInstanceStatus(context.Background(), "missing")
	if !errors.Is(err, backends.ErrInstanceNotFound) {
		t.Fatalf("GetInstanceStatus() error = %v, want backends.ErrInstanceNotFound", err)
	}
}

// The opposite mistake is worse: treating an outage as absence would create a
// second workload for an instance that already has one.
func TestGetInstanceStatusKeepsServerFailuresDistinct(t *testing.T) {
	client := testClient(t, func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "boom", http.StatusInternalServerError)
	})

	_, err := client.GetInstanceStatus(context.Background(), "instance-1")
	if err == nil {
		t.Fatal("GetInstanceStatus() error = nil, want an inspection failure")
	}
	if errors.Is(err, backends.ErrInstanceNotFound) {
		t.Fatalf("a 500 was reported as absence: %v", err)
	}
}

// Retirement is driven by control-plane records that can outlive the workload,
// so a 404 means the goal is already met. Reporting it left the instance
// permanently undeletable through the API.
func TestDeleteInstanceTreatsUnknownInstanceAsRetired(t *testing.T) {
	client := testClient(t, func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, `{"error":"unknown instance"}`, http.StatusNotFound)
	})

	if err := client.DeleteInstance(context.Background(), "missing"); err != nil {
		t.Fatalf("DeleteInstance() error = %v, want nil for an already-absent instance", err)
	}
}

func TestDeleteInstanceStillReportsRealFailures(t *testing.T) {
	client := testClient(t, func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "boom", http.StatusBadGateway)
	})

	if err := client.DeleteInstance(context.Background(), "instance-1"); err == nil {
		t.Fatal("DeleteInstance() error = nil, want the upstream failure")
	}
}
