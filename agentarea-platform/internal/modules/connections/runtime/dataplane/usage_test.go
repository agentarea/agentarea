package dataplane

import (
	"context"
	"net/http"
	"testing"
)

func TestUsageTransportPreservesLargeIntegerCounters(t *testing.T) {
	var asked string
	c := testClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		asked = r.URL.RequestURI()
		_, _ = w.Write([]byte(`{"samples":[{"resource_kind":"mcp_instance","resource_id":"i-1","cpu_usage_ns":9007199254740993,"memory_usage_bytes":18446744073709551615}]}`))
	}))
	samples, err := c.SampleResourceUsage(context.Background(), "i 1")
	if err != nil || len(samples) != 1 {
		t.Fatalf("samples %v %v", samples, err)
	}
	if asked != "/dataplane/v1/usage?resource_id=i+1" {
		t.Fatalf("asked %s", asked)
	}
	if *samples[0].CPUUsageNS != 9007199254740993 || *samples[0].MemoryUsageBytes != 18446744073709551615 {
		t.Fatalf("transport rounded integer counters: %+v", samples[0])
	}
}

func TestUsageTransportRefusesAMissingOrFailedInventory(t *testing.T) {
	if _, err := testClient(t, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{}`))
	})).SampleUsage(context.Background()); err == nil {
		t.Fatal("missing inventory became an empty successful sample")
	}
	if _, err := testClient(t, failing(http.StatusBadGateway)).SampleUsage(context.Background()); err == nil {
		t.Fatal("inventory failure was hidden")
	}
}
