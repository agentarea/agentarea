package serve

import (
	"context"
	"net/http"
	"testing"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
)

func TestRequestsAreTracedByRoute(t *testing.T) {
	spans := tracetest.NewSpanRecorder()
	tp := sdktrace.NewTracerProvider(sdktrace.WithSpanProcessor(spans))
	reader := sdkmetric.NewManualReader()
	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(reader))
	prevT, prevM, prevP := otel.GetTracerProvider(), otel.GetMeterProvider(), otel.GetTextMapPropagator()
	otel.SetTracerProvider(tp)
	otel.SetMeterProvider(mp)
	otel.SetTextMapPropagator(propagation.TraceContext{})
	t.Cleanup(func() {
		otel.SetTracerProvider(prevT)
		otel.SetMeterProvider(prevM)
		otel.SetTextMapPropagator(prevP)
	})
	mod := Module{Name: "things", Mount: func(rt Routes) error {
		rt.Mux.Handle("GET /v1/things/{thing_id}", http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(http.StatusTeapot)
		}))
		return nil
	}}
	s := edge(t, Options{}, mod)
	req, _ := http.NewRequestWithContext(t.Context(), http.MethodGet, s.URL+"/v1/things/42", nil)
	req.Header.Set("traceparent", "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	_ = resp.Body.Close()
	ended := spans.Ended()
	if len(ended) != 1 {
		t.Fatalf("%d spans", len(ended))
	}
	sp := ended[0]
	if sp.Name() != "GET /v1/things/{thing_id}" || sp.Parent().TraceID().String() != "4bf92f3577b34da6a3ce929d0e0e4736" {
		t.Fatalf("span %q parent %v", sp.Name(), sp.Parent().TraceID())
	}
	var rm metricdata.ResourceMetrics
	if err := reader.Collect(context.Background(), &rm); err != nil {
		t.Fatal(err)
	}
	found := false
	for _, sm := range rm.ScopeMetrics {
		for _, m := range sm.Metrics {
			if m.Name != "http.server.request.duration" {
				continue
			}
			for _, dp := range m.Data.(metricdata.Histogram[float64]).DataPoints {
				if v, ok := dp.Attributes.Value("http.route"); ok && v.AsString() == "/v1/things/{thing_id}" {
					found = true
				}
			}
		}
	}
	if !found {
		t.Fatalf("no request duration by route: %+v", rm.ScopeMetrics)
	}
}
