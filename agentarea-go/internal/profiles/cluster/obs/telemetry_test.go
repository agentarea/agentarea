package obs

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"sync"
	"testing"

	"go.opentelemetry.io/otel"

	"go.opentelemetry.io/otel/attribute"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"

	kernel "github.com/agentarea/agentarea/agentarea-go/internal/kernel/obs"
)

func TestLoadConfigMatchesPython(t *testing.T) {
	raw, err := os.ReadFile("testdata/telemetry.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Env    map[string]string `json:"env"`
		Result struct {
			Error           string `json:"error"`
			MetricsExporter string `json:"metrics_exporter"`
			TracesProtocol  string `json:"traces_protocol"`
			MetricsProtocol string `json:"metrics_protocol"`
			IntervalMS      int64  `json:"interval_ms"`
		} `json:"result"`
	}
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	for _, c := range cases {
		getenv := func(k string) string { return c.Env[k] }
		cfg, err := LoadConfig(getenv, "agentarea-api")
		want := c.Result
		if want.Error != "" {
			if err == nil || err.Error() != want.Error {
				t.Errorf("%v: got %v, Python %q", c.Env, err, want.Error)
			}
			continue
		}
		if err != nil {
			t.Errorf("%v: %v", c.Env, err)
			continue
		}
		if cfg.MetricsExporter != want.MetricsExporter || cfg.TracesProtocol != want.TracesProtocol ||
			cfg.MetricsProtocol != want.MetricsProtocol || cfg.ExportInterval.Milliseconds() != want.IntervalMS {
			t.Errorf("%v: got %+v, Python %+v", c.Env, cfg, want)
		}
	}
}

func TestViewKeepsTheTableAndDropsTheRest(t *testing.T) {
	reader := sdkmetric.NewManualReader()
	provider := sdkmetric.NewMeterProvider(sdkmetric.WithReader(reader), sdkmetric.WithView(View))
	meter := provider.Meter(kernel.MeterScope)
	ctx := context.Background()
	h, _ := meter.Float64Histogram(kernel.AuthzDuration)
	h.Record(ctx, 0.02, metricWith(attribute.String("operation", "check"), attribute.String("workspace_id", "ws-1")))
	other, _ := meter.Int64Counter("http.server.request.body.size")
	other.Add(ctx, 5)
	if err := RegisterUptime(provider); err != nil {
		t.Fatal(err)
	}
	var rm metricdata.ResourceMetrics
	if err := reader.Collect(ctx, &rm); err != nil {
		t.Fatal(err)
	}
	seen := map[string]metricdata.Metrics{}
	for _, sm := range rm.ScopeMetrics {
		for _, m := range sm.Metrics {
			seen[m.Name] = m
		}
	}
	if _, ok := seen["http.server.request.body.size"]; ok {
		t.Error("an instrument outside the table was exported")
	}
	if _, ok := seen[kernel.ProcessUptime]; !ok {
		t.Error("uptime missing")
	}
	hist, ok := seen[kernel.AuthzDuration].Data.(metricdata.Histogram[float64])
	if !ok || len(hist.DataPoints) != 1 {
		t.Fatalf("authz duration: %+v", seen[kernel.AuthzDuration])
	}
	dp := hist.DataPoints[0]
	if dp.Attributes.Len() != 1 || len(dp.Bounds) != 12 || dp.Bounds[0] != 0.005 {
		t.Fatalf("attributes %v bounds %v", dp.Attributes.ToSlice(), dp.Bounds)
	}
}

func TestResourceIdentity(t *testing.T) {
	t.Setenv("OTEL_RESOURCE_ATTRIBUTES", "k8s.pod.name=api-7f9,service.version=9.9.9")
	res, err := Resource(context.Background(), "agentarea-api", "1.0.0", "production")
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]string{
		"service.name": "agentarea-api", "service.namespace": "agentarea", "service.version": "9.9.9",
		"deployment.environment.name": "production",
	}
	set := res.Set()
	for k, v := range want {
		if got, _ := set.Value(attribute.Key(k)); got.String() != v {
			t.Errorf("%s = %q, want %q", k, got.String(), v)
		}
	}
	if id, _ := set.Value("service.instance.id"); len(id.String()) < len("api-7f9-1") || id.String()[:8] != "api-7f9-" {
		t.Errorf("service.instance.id %q", id.String())
	}
}

func TestSetupDisabledInstallsNothing(t *testing.T) {
	tel, err := Setup(context.Background(), Options{Enabled: false})
	if err != nil {
		t.Fatal(err)
	}
	if err := tel.Shutdown(context.Background()); err != nil {
		t.Fatal(err)
	}
	_, err = Setup(context.Background(), Options{Enabled: true, Service: "x", Getenv: func(string) string { return "" }})
	if err == nil {
		t.Fatal("enabled without an endpoint started")
	}
}

func TestSetupExportsOverOTLPHTTP(t *testing.T) {
	var mu sync.Mutex
	paths := map[string]int{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		paths[r.URL.Path]++
		mu.Unlock()
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()
	env := map[string]string{"OTEL_EXPORTER_OTLP_ENDPOINT": srv.URL}
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", srv.URL)
	ctx := context.Background()
	tel, err := Setup(ctx, Options{Enabled: true, Service: "agentarea-test", Version: "0", Environment: "test",
		Getenv: func(k string) string { return env[k] }})
	if err != nil {
		t.Fatal(err)
	}
	_, span := otel.Tracer("test").Start(ctx, "op")
	span.End()
	if err := tel.Shutdown(ctx); err != nil {
		t.Fatal(err)
	}
	mu.Lock()
	defer mu.Unlock()
	if paths["/v1/traces"] == 0 || paths["/v1/metrics"] == 0 {
		t.Fatalf("exported to %v", paths)
	}
}
