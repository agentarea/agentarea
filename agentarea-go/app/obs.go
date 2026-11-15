package app

import (
	"fmt"
	"log/slog"

	"go.opentelemetry.io/otel"

	kevents "github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	kobs "github.com/agentarea/agentarea/agentarea-go/internal/kernel/obs"
	"github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster"
	"github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster/events"
)

// registerBrokerHealth exports every configured consumer group's health, as the API process
// did (main.py start_broker_health_metrics, with telemetry on).
func registerBrokerHealth(profile *cluster.Profile, partitions int, log *slog.Logger) (func(), error) {
	reg, err := events.RegisterBrokerHealth(otel.Meter(kobs.MeterScope), profile.Broker, kevents.ConfiguredRoutes(partitions), log)
	if err != nil {
		return nil, fmt.Errorf("broker health gauges: %w", err)
	}
	return func() { _ = reg.Unregister() }, nil
}
