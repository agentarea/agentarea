package dataplane

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/usage"
)

type usageBackend struct {
	fakeBackend
	err error
}

func (b *usageBackend) SampleUsageForOwner(_ context.Context, owner string) ([]usage.Sample, error) {
	if owner != "agent-1" {
		return nil, errors.New("incorrect owner boundary")
	}
	cpu, memory := uint64(9007199254740993), uint64(18446744073709551615)
	return []usage.Sample{{Provider: "docker", ResourceKind: "mcp_instance", ResourceID: "logical-id", IncarnationID: "container-id", WorkspaceID: "workspace-1", CPUUsageNS: &cpu, MemoryUsageBytes: &memory, MemoryMetric: "usage", MeasurementStatus: "available"}}, b.err
}

func TestUsageEndpointRequiresAuthentication(t *testing.T) {
	router := newTestServer(&usageBackend{})
	for _, token := range []string{"", "wrong-token"} {
		response := request(t, router, http.MethodGet, "/dataplane/v1/usage", token, nil)
		if response.Code != http.StatusUnauthorized {
			t.Fatalf("unauthenticated usage returned %d", response.Code)
		}
	}
}

func TestUsageTransportPreservesLargeIntegerCounters(t *testing.T) {
	server := httptest.NewServer(newTestServer(&usageBackend{}))
	defer server.Close()
	client := NewClient(&ClientConfig{BaseURL: server.URL, Token: testToken})
	samples, err := client.SampleUsage(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(samples) != 1 {
		t.Fatalf("samples = %v", samples)
	}
	if samples[0].CPUUsageNS == nil || *samples[0].CPUUsageNS != 9007199254740993 || samples[0].MemoryUsageBytes == nil || *samples[0].MemoryUsageBytes != 18446744073709551615 {
		t.Fatalf("transport rounded integer counters: %+v", samples[0])
	}
}

func TestUsageInventoryFailureDoesNotBecomeEmptySuccess(t *testing.T) {
	server := httptest.NewServer(newTestServer(&usageBackend{err: errors.New("inventory unavailable")}))
	defer server.Close()
	client := NewClient(&ClientConfig{BaseURL: server.URL, Token: testToken})
	if _, err := client.SampleUsage(context.Background()); err == nil {
		t.Fatal("inventory failure was hidden")
	}
}

func TestUsageRefusesBackendWithoutOwnershipScope(t *testing.T) {
	router := newTestServer(&fakeBackend{})
	response := request(t, router, http.MethodGet, "/dataplane/v1/usage", testToken, nil)
	if response.Code != http.StatusNotImplemented {
		t.Fatalf("unscoped backend returned %d", response.Code)
	}
}

func TestUsageTransportRejectsMissingInventory(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{}`))
	}))
	defer server.Close()
	client := NewClient(&ClientConfig{BaseURL: server.URL, Token: testToken})
	if _, err := client.SampleUsage(context.Background()); err == nil {
		t.Fatal("missing inventory became empty successful sample")
	}
}

func TestResourceUsageTransportUsesNativeOwnerScopedCollection(t *testing.T) {
	path := filepath.Join(t.TempDir(), "docker")
	script := `#!/bin/sh
case "$1" in
ps)
  case "$*" in *label=agentarea.io/dataplane-id=agent-1*) ;; *) exit 1 ;; esac
  case "$*" in
    *label=agentarea.io/instance-id=logical-id*) printf '%s\n' container-id ;;
    *label=agentarea.io/instance-id=foreign-id*) exit 0 ;;
    *) exit 1 ;;
  esac
  ;;
inspect)
  printf '%s\n' '{"ID":"container-id","Labels":{"ai.agentarea.service":"mcp-one","agentarea.io/workspace-id":"workspace-1","agentarea.io/instance-id":"logical-id","agentarea.io/dataplane-id":"agent-1"},"State":{"Status":"running","Running":true,"StartedAt":"2026-01-01T00:00:00.123456789Z"},"HostConfig":{"Memory":67108864}}'
  ;;
system)
  while IFS= read -r line; do [ "${#line}" -eq 1 ] && break; done
  printf 'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n'
  printf '%s' '{"id":"container-id","read":"2026-01-01T00:00:30.987654321Z","cpu_stats":{"cpu_usage":{"total_usage":9007199254740993}},"memory_stats":{"usage":18446744073709551615}}'
  ;;
*) exit 1 ;;
esac
`
	if err := os.WriteFile(path, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	backend := backends.NewDockerBackend(&config.Config{Container: config.ContainerConfig{Runtime: path}}, slog.New(slog.NewTextHandler(io.Discard, nil)))
	server := httptest.NewServer(newTestServer(backend))
	defer server.Close()
	var sampler usage.ResourceSampler = NewClient(&ClientConfig{BaseURL: server.URL, Token: testToken})
	samples, err := sampler.SampleResourceUsage(context.Background(), "logical-id")
	if err != nil {
		t.Fatal(err)
	}
	if len(samples) != 1 || samples[0].ResourceID != "logical-id" || samples[0].CPUUsageNS == nil || *samples[0].CPUUsageNS != 9007199254740993 || samples[0].MemoryUsageBytes == nil || *samples[0].MemoryUsageBytes != 18446744073709551615 {
		t.Fatalf("targeted transport lost counters: %+v", samples)
	}
	if samples[0].StartedAt == nil || samples[0].StartedAt.Format(time.RFC3339Nano) != "2026-01-01T00:00:00.123456789Z" || samples[0].MeasurementAt == nil || samples[0].MeasurementAt.Format(time.RFC3339Nano) != "2026-01-01T00:00:30.987654321Z" {
		t.Fatalf("targeted transport lost timestamps: %+v", samples[0])
	}
	samples, err = sampler.SampleResourceUsage(context.Background(), "foreign-id")
	if err != nil || samples == nil || len(samples) != 0 {
		t.Fatalf("foreign resource inventory: samples=%v err=%v", samples, err)
	}
}

func TestResourceUsageRefusesUntargetedOwnerCapability(t *testing.T) {
	router := newTestServer(&usageBackend{})
	response := request(t, router, http.MethodGet, "/dataplane/v1/usage?resource_id=logical-id", testToken, nil)
	if response.Code != http.StatusNotImplemented {
		t.Fatalf("untargeted capability returned %d", response.Code)
	}
}

func TestResourceUsageRejectsEmptyTarget(t *testing.T) {
	router := newTestServer(&usageBackend{})
	response := request(t, router, http.MethodGet, "/dataplane/v1/usage?resource_id=", testToken, nil)
	if response.Code != http.StatusBadRequest {
		t.Fatalf("empty target returned %d", response.Code)
	}
}
