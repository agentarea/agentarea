package telemetry

import (
	"context"
	"strings"
	"testing"
	"time"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/metric"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
)

func TestSetupRejectsUnknownMetricsExporter(t *testing.T) {
	t.Setenv(endpointEnv, "http://collector:4318")
	t.Setenv(metricsExporterEnv, "statsd")
	if _, err := Setup(context.Background(), true, "test"); err == nil {
		t.Fatal("Setup accepted OTEL_METRICS_EXPORTER=statsd")
	}
}

func TestCheckEndpoints(t *testing.T) {
	cases := []struct {
		name    string
		env     map[string]string
		missing string
	}{
		{name: "shared endpoint", env: map[string]string{endpointEnv: "http://gateway:4318"}},
		{name: "nothing set", env: map[string]string{}, missing: endpointEnv},
		{name: "both signal endpoints", env: map[string]string{tracesEndpointEnv: "http://t", metricsEndpointEnv: "http://m"}},
		{name: "traces endpoint only", env: map[string]string{tracesEndpointEnv: "http://t"}, missing: metricsEndpointEnv},
		{name: "metrics pulled, traces endpoint", env: map[string]string{metricsExporterEnv: "prometheus", tracesEndpointEnv: "http://t"}},
		{name: "both exporters off", env: map[string]string{metricsExporterEnv: "none", tracesExporterEnv: "none"}},
		{name: "explicit otlp without endpoint", env: map[string]string{metricsExporterEnv: "otlp", tracesExporterEnv: "none"}, missing: metricsEndpointEnv},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := checkEndpoints(func(name string) string { return tc.env[name] })
			if tc.missing == "" {
				if err != nil {
					t.Fatalf("unexpected error: %v", err)
				}
				return
			}
			if err == nil || !strings.Contains(err.Error(), endpointEnv) || !strings.Contains(err.Error(), tc.missing) {
				t.Fatalf("error = %v, want it to name %s and %s", err, endpointEnv, tc.missing)
			}
		})
	}
}

func TestExportInterval(t *testing.T) {
	cases := []struct {
		raw     string
		want    time.Duration
		wantErr bool
	}{
		{raw: "", want: 15 * time.Second},
		{raw: "60000", want: time.Minute},
		{raw: "15s", wantErr: true},
		{raw: "0", wantErr: true},
	}
	for _, tc := range cases {
		got, err := exportInterval(func(string) string { return tc.raw })
		if (err != nil) != tc.wantErr || got != tc.want {
			t.Fatalf("exportInterval(%q) = %s, %v", tc.raw, got, err)
		}
	}
}

func TestViewsKeepOnlyAllowedAttributesAndBuckets(t *testing.T) {
	reader := sdkmetric.NewManualReader()
	provider := sdkmetric.NewMeterProvider(sdkmetric.WithReader(reader), sdkmetric.WithView(sdkViews()...))
	meter := provider.Meter("test")
	ctx := context.Background()
	leaked := attribute.String("agentarea.mcp.instance_id", "8ca9f331")
	coldStart, _ := meter.Float64Histogram(MCPColdStartDuration)
	coldStart.Record(ctx, 12, metric.WithAttributes(AttrPhase.String("total"), AttrOutcome.String("ready"), AttrPlane.String("remote"), leaked))
	requests, _ := meter.Int64Counter(MCPGatewayRequests)
	requests.Add(ctx, 1, metric.WithAttributes(AttrMCPMethod.String("tools/call"), AttrStatus.String("2xx"), AttrCold.Bool(true), leaked))
	server, _ := meter.Float64Histogram(httpServerDuration)
	server.Record(ctx, 0.2, metric.WithAttributes(
		attribute.String("http.request.method", "POST"), attribute.String("http.route", "/mcp/:instance_id/mcp"),
		attribute.Int("http.response.status_code", 200), attribute.String("server.address", "mcp-manager"),
	))
	body, _ := meter.Int64Histogram(httpServerRequestBytes)
	body.Record(ctx, 512)

	var collected metricdata.ResourceMetrics
	if err := reader.Collect(ctx, &collected); err != nil {
		t.Fatal(err)
	}
	cases := []struct {
		name    string
		keys    []attribute.Key
		buckets []float64
	}{
		{name: MCPColdStartDuration, keys: []attribute.Key{AttrPhase, AttrOutcome, AttrPlane}, buckets: coldStartBuckets},
		{name: MCPGatewayRequests, keys: []attribute.Key{AttrMCPMethod, AttrStatus, AttrCold}},
		{name: httpServerDuration, keys: []attribute.Key{"http.request.method", "http.route", "http.response.status_code"}, buckets: httpServerBuckets},
	}
	exported := map[string]metricdata.Aggregation{}
	for _, m := range collected.ScopeMetrics[0].Metrics {
		exported[m.Name] = m.Data
	}
	if _, ok := exported[httpServerRequestBytes]; ok {
		t.Fatalf("%s is exported, want it dropped", httpServerRequestBytes)
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var set attribute.Set
			switch data := exported[tc.name].(type) {
			case metricdata.Sum[int64]:
				set = data.DataPoints[0].Attributes
			case metricdata.Histogram[float64]:
				set = data.DataPoints[0].Attributes
				if got := data.DataPoints[0].Bounds; len(got) != len(tc.buckets) || got[len(got)-1] != tc.buckets[len(tc.buckets)-1] {
					t.Fatalf("buckets = %v, want %v", got, tc.buckets)
				}
			default:
				t.Fatalf("not exported: %T", data)
			}
			if set.Len() != len(tc.keys) {
				t.Fatalf("attributes = %v, want only %v", set.ToSlice(), tc.keys)
			}
			for _, key := range tc.keys {
				if !set.HasValue(key) {
					t.Fatalf("lost %s", key)
				}
			}
		})
	}
}
