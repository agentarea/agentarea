package sandboxruntime

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestProviderUsagePreservesAllocationWithoutInventingActualMetrics(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet || r.URL.Path != "/v2/sandboxes" {
			http.Error(w, "unexpected operation", http.StatusBadRequest)
			return
		}
		_, _ = w.Write([]byte(`[
			{"sandboxID":"owned","state":"running","cpuCount":2,"memoryMB":512,"startedAt":"2026-09-18T12:00:00.123Z","endAt":"2026-09-18T12:05:00Z","envdAccessToken":"secret-token","metadata":{"agentarea.provisioning_id":"provision-1","agentarea.workspace_id":"workspace-1","agentarea.task_id":"task-1"}},
			{"sandboxID":"unmanaged","state":"running","cpuCount":8,"metadata":{}}
		]`))
	}))
	defer server.Close()
	provider, err := NewE2BProvider(E2BConfig{
		ProviderName: "e2b", APIURL: server.URL, APIKey: "e2b_test", SandboxURL: server.URL,
		Template: "runtime-template", LeaseTTL: 15 * time.Minute, AllowInternetAccess: true,
		AllowInsecure: true, Isolation: "firecracker", AttestationPath: DefaultIsolationAttestationPath,
	}, http.DefaultTransport)
	if err != nil {
		t.Fatal(err)
	}
	samples, err := NewAllocationSampler(provider, "e2b").SampleUsage(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(samples) != 1 || samples[0].IncarnationID != "owned" || samples[0].WorkspaceID != "workspace-1" {
		t.Fatalf("usage inventory included an unowned allocation: %+v", samples)
	}
	sample := samples[0]
	if sample.ProviderResources["cpu"] != "2" || sample.ProviderResources["memory"] != "512Mi" || sample.ProviderResourcesSource != "provider_readback" {
		t.Fatalf("provider allocation semantics lost: %+v", sample)
	}
	if sample.MeasurementStatus != "unavailable" || sample.CPUUsageNS != nil || sample.MemoryUsageBytes != nil || sample.CPULimitNanocores != nil || sample.CPURequestNanocores != nil {
		t.Fatalf("invented actual/request/limit metrics: %+v", sample)
	}
	if sample.StartedAt == nil || sample.StartedAt.Nanosecond() != 123000000 || sample.ExpiresAt == nil {
		t.Fatalf("provider timestamps lost: %+v", sample)
	}
	encoded, err := json.Marshal(sample)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(encoded), "secret-token") {
		t.Fatal("provider access token leaked into usage")
	}
	if _, err := provider.List(context.Background(), ""); err == nil {
		t.Fatal("public inventory accepted an unscoped workspace")
	}
	if _, err := NewAllocationSampler(provider, "opensandbox").SampleUsage(context.Background()); err == nil {
		t.Fatal("inventory attributed to another provider was accepted")
	}
}
