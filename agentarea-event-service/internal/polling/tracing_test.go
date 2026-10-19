package polling

import (
	"context"
	"errors"
	"testing"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/codes"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
	"go.opentelemetry.io/otel/trace/noop"

	"github.com/agentarea/event-service/internal/transport"
)

func recordSpans(t *testing.T) *tracetest.SpanRecorder {
	t.Helper()
	recorder := tracetest.NewSpanRecorder()
	otel.SetTracerProvider(sdktrace.NewTracerProvider(sdktrace.WithSpanProcessor(recorder)))
	t.Cleanup(func() { otel.SetTracerProvider(noop.NewTracerProvider()) })
	return recorder
}

func TestAPollSpanRecordsTheSourceTransportAndError(t *testing.T) {
	recorder := recordSpans(t)
	pollErr := errors.New("HTTP 502")
	tr := &fixedTransport{err: pollErr}
	m := newManager(newFakeSources(), &fakePublisher{}, &fakeCaller{}, tr)

	if _, _, err := m.pollOnce(context.Background(), pollSource(), tr, ""); err == nil {
		t.Fatal("pollOnce hid the transport error")
	}
	ended := recorder.Ended()
	if len(ended) != 1 {
		t.Fatalf("ended spans = %d, want 1", len(ended))
	}
	attrs := map[string]string{}
	for _, kv := range ended[0].Attributes() {
		attrs[string(kv.Key)] = kv.Value.String()
	}
	if attrs["agentarea.source.id"] != "src-1" || attrs["agentarea.source.transport"] != "fixed" {
		t.Fatalf("attributes = %v", attrs)
	}
	if ended[0].Status().Code != codes.Error {
		t.Fatalf("status = %+v", ended[0].Status())
	}
}

func TestAPollSpanCountsItems(t *testing.T) {
	recorder := recordSpans(t)
	tr := &fixedTransport{result: transport.Result{Items: []any{1, 2}}}
	m := newManager(newFakeSources(), &fakePublisher{}, &fakeCaller{}, tr)

	if _, _, err := m.pollOnce(context.Background(), pollSource(), tr, ""); err != nil {
		t.Fatalf("pollOnce: %v", err)
	}
	for _, kv := range recorder.Ended()[0].Attributes() {
		if kv.Key == "agentarea.poll.items_fetched" && kv.Value.AsInt64() == 2 {
			return
		}
	}
	t.Fatal("items_fetched is not 2")
}
