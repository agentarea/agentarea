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

	"github.com/agentarea/event-service/internal/channels"
	"github.com/agentarea/event-service/internal/trigger"
)

func recordSpans(t *testing.T) *tracetest.SpanRecorder {
	t.Helper()
	recorder := tracetest.NewSpanRecorder()
	otel.SetTracerProvider(sdktrace.NewTracerProvider(sdktrace.WithSpanProcessor(recorder)))
	t.Cleanup(func() { otel.SetTracerProvider(noop.NewTracerProvider()) })
	return recorder
}

type pollerFunc func(ctx context.Context, offset int64) (*channels.PollResult, error)

func (f pollerFunc) Poll(ctx context.Context, offset int64) (*channels.PollResult, error) {
	return f(ctx, offset)
}

func TestPollTickSpanRecordsSourceAndError(t *testing.T) {
	recorder := recordSpans(t)

	ctx, cancel := context.WithCancel(context.Background())
	pollErr := errors.New("getUpdates HTTP 502")
	poller := pollerFunc(func(context.Context, int64) (*channels.PollResult, error) {
		cancel()
		return nil, pollErr
	})

	m := &Manager{}
	m.runPoller(ctx, trigger.Trigger{ID: "trigger-1", DataExtractor: "telegram_polling"}, poller)

	ended := recorder.Ended()
	if len(ended) != 1 {
		t.Fatalf("ended spans = %d, want 1", len(ended))
	}
	span := ended[0]
	attrs := map[string]string{}
	for _, kv := range span.Attributes() {
		attrs[string(kv.Key)] = kv.Value.String()
	}
	if attrs["agentarea.source.id"] != "trigger-1" || attrs["agentarea.source.transport"] != "telegram_polling" {
		t.Fatalf("attributes = %v", attrs)
	}
	if span.Status().Code != codes.Error || span.Status().Description != pollErr.Error() {
		t.Fatalf("status = %+v, want error %q", span.Status(), pollErr)
	}
}

func TestPollTickSpanCountsItemsFetched(t *testing.T) {
	recorder := recordSpans(t)

	ctx, cancel := context.WithCancel(context.Background())
	poller := pollerFunc(func(context.Context, int64) (*channels.PollResult, error) {
		cancel()
		return &channels.PollResult{}, nil
	})

	m := &Manager{}
	m.runPoller(ctx, trigger.Trigger{ID: "trigger-1", DataExtractor: "telegram_polling"}, poller)

	ended := recorder.Ended()
	if len(ended) != 1 {
		t.Fatalf("ended spans = %d, want 1", len(ended))
	}
	for _, kv := range ended[0].Attributes() {
		if kv.Key == "agentarea.poll.items_fetched" {
			if kv.Value.AsInt64() != 0 {
				t.Fatalf("items_fetched = %d, want 0", kv.Value.AsInt64())
			}
			return
		}
	}
	t.Fatal("items_fetched attribute missing")
}
