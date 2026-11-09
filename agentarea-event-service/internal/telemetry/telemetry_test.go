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

func TestSetupDisabledInstallsNothing(t *testing.T) {
	shutdown, err := Setup(context.Background(), false, "test")
	if err != nil {
		t.Fatalf("Setup returned error: %v", err)
	}
	if err := shutdown(context.Background()); err != nil {
		t.Fatalf("shutdown returned error: %v", err)
	}
	_, span := Tracer().Start(context.Background(), "probe")
	defer span.End()
	if span.IsRecording() {
		t.Fatal("span records with telemetry disabled")
	}
}

func TestSetupRejectsUnknownProtocol(t *testing.T) {
	t.Setenv(endpointEnv, "http://collector:4318")
	t.Setenv(protocolEnv, "http/json")
	if _, err := Setup(context.Background(), true, "test"); err == nil {
		t.Fatal("Setup accepted OTEL_EXPORTER_OTLP_PROTOCOL=http/json")
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
	leaked := attribute.String("agentarea.source.id", "src-1")
	polls, _ := meter.Int64Counter(EventPolls)
	polls.Add(context.Background(), 1, metric.WithAttributes(AttrTransport.String("http"), AttrOutcome.String("ok"), leaked))
	duration, _ := meter.Float64Histogram(EventPollDuration)
	duration.Record(context.Background(), 0.2, metric.WithAttributes(AttrTransport.String("http"), leaked))

	var collected metricdata.ResourceMetrics
	if err := reader.Collect(context.Background(), &collected); err != nil {
		t.Fatal(err)
	}
	cases := map[string][]attribute.Key{
		EventPolls:        {AttrTransport, AttrOutcome},
		EventPollDuration: {AttrTransport},
	}
	for _, m := range collected.ScopeMetrics[0].Metrics {
		want, ok := cases[m.Name]
		if !ok {
			continue
		}
		delete(cases, m.Name)
		var set attribute.Set
		switch data := m.Data.(type) {
		case metricdata.Sum[int64]:
			set = data.DataPoints[0].Attributes
		case metricdata.Histogram[float64]:
			set = data.DataPoints[0].Attributes
			if got := data.DataPoints[0].Bounds; len(got) != len(pollBuckets) || got[len(got)-1] != 30 {
				t.Fatalf("%s buckets = %v", m.Name, got)
			}
		}
		if set.Len() != len(want) {
			t.Fatalf("%s attributes = %v, want only %v", m.Name, set.ToSlice(), want)
		}
		for _, key := range want {
			if !set.HasValue(key) {
				t.Fatalf("%s lost %s", m.Name, key)
			}
		}
	}
	if len(cases) != 0 {
		t.Fatalf("not collected: %v", cases)
	}
}
