package events

import (
	"context"
	"errors"
	"log/slog"
	"testing"
	"time"

	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"

	kernel "github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	kobs "github.com/agentarea/agentarea/agentarea-go/internal/kernel/obs"
)

type healthBroker struct {
	kernel.Broker
	fail bool
}

func (h *healthBroker) GroupInfo(_ context.Context, stream, group string) (*kernel.GroupInfo, error) {
	if h.fail {
		return nil, errors.New("redis down")
	}
	if stream == kernel.StreamsIngest {
		return &kernel.GroupInfo{Lag: 7}, nil
	}
	return nil, nil
}

func (h *healthBroker) Pending(context.Context, string, string) (kernel.PendingSummary, error) {
	age := 3 * time.Second
	return kernel.PendingSummary{Count: 2, OldestAge: &age}, nil
}

func (h *healthBroker) Length(_ context.Context, stream string) (int64, error) {
	if stream == kernel.DeadLetterTopic(kernel.StreamEvents, kernel.RouterGroup) {
		return 5, nil
	}
	return 0, nil
}

func collect(t *testing.T, r *sdkmetric.ManualReader) map[string][]metricdata.DataPoint[int64] {
	t.Helper()
	var rm metricdata.ResourceMetrics
	if err := r.Collect(context.Background(), &rm); err != nil {
		t.Fatal(err)
	}
	out := map[string][]metricdata.DataPoint[int64]{}
	for _, sm := range rm.ScopeMetrics {
		for _, m := range sm.Metrics {
			if g, ok := m.Data.(metricdata.Gauge[int64]); ok {
				out[m.Name] = g.DataPoints
			}
			if g, ok := m.Data.(metricdata.Gauge[float64]); ok {
				for _, dp := range g.DataPoints {
					out[m.Name] = append(out[m.Name], metricdata.DataPoint[int64]{Attributes: dp.Attributes, Value: int64(dp.Value)})
				}
			}
		}
	}
	return out
}

func TestBrokerHealthGauges(t *testing.T) {
	reader := sdkmetric.NewManualReader()
	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(reader))
	b := &healthBroker{}
	reg, err := RegisterBrokerHealth(mp.Meter("t"), b, kernel.ConfiguredRoutes(2), slog.New(slog.DiscardHandler))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = reg.Unregister() }()
	got := collect(t, reader)
	if len(got[kobs.BrokerGroupLag]) != 1 || got[kobs.BrokerGroupLag][0].Value != 7 {
		t.Fatalf("lag %v", got[kobs.BrokerGroupLag])
	}
	if v, _ := got[kobs.BrokerGroupLag][0].Attributes.Value(kobs.AttrGroup); v.AsString() != kernel.IngestGroup {
		t.Errorf("lag labels %v", got[kobs.BrokerGroupLag][0].Attributes)
	}
	if got[kobs.BrokerGroupPending][0].Value != 2 || got[kobs.BrokerGroupOldestPending][0].Value != 3 {
		t.Errorf("pending %v oldest %v", got[kobs.BrokerGroupPending], got[kobs.BrokerGroupOldestPending])
	}
	if n := len(got[kobs.BrokerDLQLength]); n != 6 {
		t.Errorf("%d dead-letter streams, want 6 distinct", n)
	}
	if got[kobs.BrokerHealth][0].Value != 1 {
		t.Errorf("health %v", got[kobs.BrokerHealth])
	}
	b.fail = true
	got = collect(t, reader)
	if got[kobs.BrokerHealth][0].Value != 0 || len(got[kobs.BrokerGroupLag]) != 0 {
		t.Fatalf("a failed read: %v", got)
	}
}
