package polling

import (
	"context"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/metric"

	"github.com/agentarea/event-service/internal/telemetry"
)

// Poller states for the pollers gauge.
const (
	pollerPolling      = "polling"
	pollerWaiting      = "waiting"
	pollerOverCapacity = "over_capacity"
)

// Poll steps; a failed poll's outcome names the step that failed.
const (
	stepCredentials = "credentials"
	stepFetch       = "fetch"
	stepPublish     = "publish"
	stepRecord      = "record"
)

// pollMetrics are the poll manager's instruments (ADR-0048 §9). The transport
// attribute is a registered transport name, never a source or workspace.
type pollMetrics struct {
	polls     metric.Int64Counter
	duration  metric.Float64Histogram
	published metric.Int64Counter
}

func newPollMetrics(m *Manager) pollMetrics {
	meter := telemetry.Meter()
	var metrics pollMetrics
	var err error
	if metrics.polls, err = meter.Int64Counter(telemetry.EventPolls,
		metric.WithUnit("{poll}"), metric.WithDescription("Polls of a source, by how they ended.")); err != nil {
		otel.Handle(err)
	}
	if metrics.duration, err = meter.Float64Histogram(telemetry.EventPollDuration,
		metric.WithUnit("s"), metric.WithDescription("Duration of one poll of a source.")); err != nil {
		otel.Handle(err)
	}
	if metrics.published, err = meter.Int64Counter(telemetry.EventItemsPublished,
		metric.WithUnit("{item}"), metric.WithDescription("Polled items published to ingest.")); err != nil {
		otel.Handle(err)
	}
	if _, err = meter.Int64ObservableGauge(telemetry.EventPollers,
		metric.WithUnit("{poller}"), metric.WithDescription("Pollers of this replica, by state."),
		metric.WithInt64Callback(m.observePollers)); err != nil {
		otel.Handle(err)
	}
	return metrics
}

func (p pollMetrics) poll(ctx context.Context, transport, outcome string, elapsed time.Duration) {
	p.polls.Add(ctx, 1, metric.WithAttributes(telemetry.AttrTransport.String(transport), telemetry.AttrOutcome.String(outcome)))
	p.duration.Record(ctx, elapsed.Seconds(), metric.WithAttributes(telemetry.AttrTransport.String(transport)))
}

func (p pollMetrics) itemPublished(ctx context.Context, transport string) {
	p.published.Add(ctx, 1, metric.WithAttributes(telemetry.AttrTransport.String(transport)))
}

// pollOutcome is ok, canceled when the poller was stopped mid-poll, or the
// failed step with a _failed suffix.
func pollOutcome(step string, err error, canceled bool) string {
	switch {
	case err == nil:
		return "ok"
	case canceled:
		return "canceled"
	default:
		return step + "_failed"
	}
}

func (m *Manager) observePollers(_ context.Context, observer metric.Int64Observer) error {
	m.mu.Lock()
	var polling, waiting int64
	for _, p := range m.pollers {
		if p.polling.Load() {
			polling++
		} else {
			waiting++
		}
	}
	overCapacity := int64(m.overCapacity)
	m.mu.Unlock()
	observer.Observe(polling, metric.WithAttributes(telemetry.AttrState.String(pollerPolling)))
	observer.Observe(waiting, metric.WithAttributes(telemetry.AttrState.String(pollerWaiting)))
	observer.Observe(overCapacity, metric.WithAttributes(telemetry.AttrState.String(pollerOverCapacity)))
	return nil
}
