package polling

import (
	"context"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/metric"

	kobs "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/obs"
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

func newPollMetrics(m *Manager, meter metric.Meter) pollMetrics {
	var metrics pollMetrics
	var err error
	if metrics.polls, err = meter.Int64Counter(kobs.EventPolls,
		metric.WithUnit("{poll}"), metric.WithDescription("Polls of a source, by how they ended.")); err != nil {
		otel.Handle(err)
	}
	if metrics.duration, err = meter.Float64Histogram(kobs.EventPollDuration,
		metric.WithUnit("s"), metric.WithDescription("Duration of one poll of a source.")); err != nil {
		otel.Handle(err)
	}
	if metrics.published, err = meter.Int64Counter(kobs.EventItemsPublished,
		metric.WithUnit("{item}"), metric.WithDescription("Polled items published to ingest.")); err != nil {
		otel.Handle(err)
	}
	if _, err = meter.Int64ObservableGauge(kobs.EventPollers,
		metric.WithUnit("{poller}"), metric.WithDescription("Pollers of this replica, by state."),
		metric.WithInt64Callback(m.observePollers)); err != nil {
		otel.Handle(err)
	}
	return metrics
}

func (p pollMetrics) poll(ctx context.Context, transport, outcome string, elapsed time.Duration) {
	p.polls.Add(ctx, 1, metric.WithAttributes(attribute.String(kobs.AttrTransport, transport), attribute.String(kobs.AttrOutcome, outcome)))
	p.duration.Record(ctx, elapsed.Seconds(), metric.WithAttributes(attribute.String(kobs.AttrTransport, transport)))
}

func (p pollMetrics) itemPublished(ctx context.Context, transport string) {
	p.published.Add(ctx, 1, metric.WithAttributes(attribute.String(kobs.AttrTransport, transport)))
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
	observer.Observe(polling, metric.WithAttributes(attribute.String(kobs.AttrState, pollerPolling)))
	observer.Observe(waiting, metric.WithAttributes(attribute.String(kobs.AttrState, pollerWaiting)))
	observer.Observe(overCapacity, metric.WithAttributes(attribute.String(kobs.AttrState, pollerOverCapacity)))
	return nil
}
