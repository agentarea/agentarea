package tracing

import (
	"context"
	"testing"
)

func TestSetupDisabledInstallsNothing(t *testing.T) {
	shutdown, err := Setup(context.Background(), false)
	if err != nil {
		t.Fatalf("Setup returned error: %v", err)
	}
	if err := shutdown(context.Background()); err != nil {
		t.Fatalf("shutdown returned error: %v", err)
	}
	_, span := Tracer().Start(context.Background(), "probe")
	defer span.End()
	if span.IsRecording() {
		t.Fatal("span records with tracing disabled")
	}
}

func TestSetupRejectsUnknownProtocol(t *testing.T) {
	t.Setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/json")
	if _, err := Setup(context.Background(), true); err == nil {
		t.Fatal("Setup accepted OTEL_EXPORTER_OTLP_PROTOCOL=http/json")
	}
}
