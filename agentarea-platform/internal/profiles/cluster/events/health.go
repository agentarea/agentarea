package events

import (
	"context"
	"log/slog"
	"time"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/metric"

	kernel "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	kobs "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/obs"
)

// healthReadTimeout bounds one collection's read of the broker (broker_metrics.py).
const healthReadTimeout = 5 * time.Second

// GroupHealth is one existing group's position and what it holds unacknowledged.
type GroupHealth struct {
	Route   kernel.GroupRoute
	Info    kernel.GroupInfo
	Pending kernel.PendingSummary
}

// BrokerHealth is every existing group's health and each dead-letter stream's length.
type BrokerHealth struct {
	Groups      []GroupHealth
	DeadLetters []DeadLetterLength
}

// DeadLetterLength is the length of one dead-letter stream.
type DeadLetterLength struct {
	Stream string
	Length int64
}

// ReadBrokerHealth reads each route's group; a group whose consumer has not started has no
// position and is left out.
func ReadBrokerHealth(ctx context.Context, b kernel.Broker, routes []kernel.GroupRoute) (BrokerHealth, error) {
	var h BrokerHealth
	seen := map[string]bool{}
	for _, r := range routes {
		info, err := b.GroupInfo(ctx, r.Stream, r.Group)
		if err != nil {
			return BrokerHealth{}, err
		}
		if info != nil {
			pending, err := b.Pending(ctx, r.Stream, r.Group)
			if err != nil {
				return BrokerHealth{}, err
			}
			h.Groups = append(h.Groups, GroupHealth{Route: r, Info: *info, Pending: pending})
		}
		if seen[r.DLQ] {
			continue
		}
		seen[r.DLQ] = true
		n, err := b.Length(ctx, r.DLQ)
		if err != nil {
			return BrokerHealth{}, err
		}
		h.DeadLetters = append(h.DeadLetters, DeadLetterLength{Stream: r.DLQ, Length: n})
	}
	return h, nil
}

// RegisterBrokerHealth exports consumer-group lag, pending, oldest pending age, dead-letter
// lengths and agentarea.broker.health, read from the broker on each collection; health is 0
// when the read fails.
func RegisterBrokerHealth(m metric.Meter, b kernel.Broker, routes []kernel.GroupRoute, log *slog.Logger) (metric.Registration, error) {
	lag, err := m.Int64ObservableGauge(kobs.BrokerGroupLag, metric.WithUnit("{entry}"),
		metric.WithDescription("Entries in the stream not yet delivered to the consumer group."))
	if err != nil {
		return nil, err
	}
	pending, err := m.Int64ObservableGauge(kobs.BrokerGroupPending, metric.WithUnit("{entry}"),
		metric.WithDescription("Entries delivered to the consumer group and not yet acknowledged."))
	if err != nil {
		return nil, err
	}
	oldest, err := m.Float64ObservableGauge(kobs.BrokerGroupOldestPending, metric.WithUnit("s"),
		metric.WithDescription("Age of the oldest entry the consumer group holds pending; a redelivery does not reset it."))
	if err != nil {
		return nil, err
	}
	dlq, err := m.Int64ObservableGauge(kobs.BrokerDLQLength, metric.WithUnit("{entry}"),
		metric.WithDescription("Entries in the dead-letter stream."))
	if err != nil {
		return nil, err
	}
	health, err := m.Int64ObservableGauge(kobs.BrokerHealth,
		metric.WithDescription("1 when the last collection read consumer-group health from the broker, else 0."))
	if err != nil {
		return nil, err
	}
	return m.RegisterCallback(func(ctx context.Context, o metric.Observer) error {
		ctx, cancel := context.WithTimeout(ctx, healthReadTimeout)
		defer cancel()
		h, err := ReadBrokerHealth(ctx, b, routes)
		if err != nil {
			log.WarnContext(ctx, "Reading consumer-group health from the broker failed", "error", err)
			o.ObserveInt64(health, 0)
			return nil
		}
		for _, g := range h.Groups {
			labels := metric.WithAttributes(attribute.String(kobs.AttrStream, g.Route.Stream), attribute.String(kobs.AttrGroup, g.Route.Group))
			o.ObserveInt64(lag, g.Info.Lag, labels)
			o.ObserveInt64(pending, g.Pending.Count, labels)
			age := 0.0
			if g.Pending.OldestAge != nil {
				age = g.Pending.OldestAge.Seconds()
			}
			o.ObserveFloat64(oldest, age, labels)
		}
		for _, d := range h.DeadLetters {
			o.ObserveInt64(dlq, d.Length, metric.WithAttributes(attribute.String(kobs.AttrStream, d.Stream)))
		}
		o.ObserveInt64(health, 1)
		return nil
	}, lag, pending, oldest, dlq, health)
}
