package submit

import (
	"context"
	"testing"

	"go.opentelemetry.io/otel"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
	"go.opentelemetry.io/otel/trace"
	"go.opentelemetry.io/otel/trace/noop"
)

func recordSpans(t *testing.T) *tracetest.SpanRecorder {
	t.Helper()
	recorder := tracetest.NewSpanRecorder()
	otel.SetTracerProvider(sdktrace.NewTracerProvider(sdktrace.WithSpanProcessor(recorder)))
	t.Cleanup(func() { otel.SetTracerProvider(noop.NewTracerProvider()) })
	return recorder
}

func TestSubmitCarriesTraceparentOfSubmitSpan(t *testing.T) {
	recorder := recordSpans(t)
	ctx, parent := otel.Tracer("test").Start(context.Background(), "poll")
	defer parent.End()

	b := &fakeBroker{}
	err := NewStreamSubmitter(b, "").SubmitEvent(ctx, "trigger-1",
		Event{Type: "message", ChatID: 1, MessageID: 2},
		map[string]any{"type": "telegram"})
	if err != nil {
		t.Fatalf("SubmitEvent returned error: %v", err)
	}

	ended := recorder.Ended()
	if len(ended) != 1 {
		t.Fatalf("ended spans = %d, want 1", len(ended))
	}
	submitSpan := ended[0]
	if submitSpan.SpanKind() != trace.SpanKindProducer {
		t.Fatalf("span kind = %s, want producer", submitSpan.SpanKind())
	}
	if submitSpan.Parent().SpanID() != parent.SpanContext().SpanID() {
		t.Fatal("submit span is not a child of the poll span")
	}

	sc := submitSpan.SpanContext()
	want := "00-" + sc.TraceID().String() + "-" + sc.SpanID().String() + "-01"
	if got := b.fields["traceparent"]; got != want {
		t.Fatalf("traceparent = %q, want %q", got, want)
	}
}

func TestSubmitOmitsTraceparentWhenTracingIsOff(t *testing.T) {
	otel.SetTracerProvider(noop.NewTracerProvider())

	b := &fakeBroker{}
	err := NewStreamSubmitter(b, "").SubmitEvent(context.Background(), "trigger-1",
		Event{Type: "message", ChatID: 1, MessageID: 2}, nil)
	if err != nil {
		t.Fatalf("SubmitEvent returned error: %v", err)
	}
	if v, ok := b.fields["traceparent"]; ok {
		t.Fatalf("traceparent = %q with no span in context", v)
	}
}
