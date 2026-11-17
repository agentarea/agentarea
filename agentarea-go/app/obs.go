package app

import (
	"context"
	"fmt"
	"log/slog"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/metric"

	kevents "github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/lifecycle"
	kobs "github.com/agentarea/agentarea/agentarea-go/internal/kernel/obs"
	"github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster"
	"github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster/events"
)

// brokerHealth exports every configured consumer group's health while the process runs, as the
// API process did (main.py start_broker_health_metrics, with telemetry on).
func brokerHealth(profile *cluster.Profile, partitions int, log *slog.Logger) lifecycle.Component {
	var reg metric.Registration
	return lifecycle.Func("broker health metrics", func(context.Context) error {
		r, err := events.RegisterBrokerHealth(otel.Meter(kobs.MeterScope), profile.Broker, kevents.ConfiguredRoutes(partitions), log)
		if err != nil {
			return fmt.Errorf("broker health gauges: %w", err)
		}
		reg = r
		return nil
	}, func(context.Context) error {
		if reg == nil {
			return nil
		}
		return reg.Unregister()
	})
}
