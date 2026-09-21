package mcpgateway

import (
	"context"
	"encoding/json"
	"errors"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/usage"
)

type boundaryBackendStub struct {
	*runtimeBackendStub
	sample func(context.Context, string) ([]usage.Sample, error)
}

func (b *boundaryBackendStub) SampleResourceUsage(ctx context.Context, id string) ([]usage.Sample, error) {
	return b.sample(ctx, id)
}

type boundaryProviderStub struct {
	runtimeProviderStub
	beforeDelete func()
}

func (p *boundaryProviderStub) DeleteInstance(ctx context.Context, id, name string) error {
	p.beforeDelete()
	return p.runtimeProviderStub.DeleteInstance(ctx, id, name)
}

type boundaryRecorderFunc func(context.Context, usage.Event) error

func (f boundaryRecorderFunc) Record(ctx context.Context, event usage.Event) error {
	return f(ctx, event)
}

func TestShortLivedRuntimeRetainsActivationAndDeletionSamples(t *testing.T) {
	instance := dockerInstance()
	instance.WorkspaceID = "workspace"
	recorder := &usageRecorderStub{}
	measurementAt := time.Now().UTC()
	limit, cpu, memory := int64(512<<20), uint64(123), uint64(456)
	calls := 0
	statusBackend := &runtimeBackendStub{statuses: []statusReply{{err: backends.ErrInstanceNotFound}, {status: "running"}}}
	backend := &boundaryBackendStub{
		runtimeBackendStub: statusBackend,
		sample: func(ctx context.Context, id string) ([]usage.Sample, error) {
			if _, ok := ctx.Deadline(); !ok {
				t.Fatal("sampling context is not bounded")
			}
			if id != instance.InstanceID {
				t.Fatalf("sample resource = %q", id)
			}
			if statusBackend.statusCalls() < 2 {
				t.Fatal("sample preceded physical readiness observation")
			}
			calls++
			return []usage.Sample{{Provider: "docker", ResourceKind: "mcp_instance", ResourceID: id,
				WorkspaceID: instance.WorkspaceID, IncarnationID: "physical-container", State: "running",
				ObservedAt: measurementAt, MeasurementAt: &measurementAt, MemoryLimitBytes: &limit,
				CPUUsageNS: &cpu, MemoryUsageBytes: &memory, MemoryMetric: "usage", MeasurementStatus: "available"}}, nil
		},
	}
	provider := &boundaryProviderStub{beforeDelete: func() {
		events := recorder.snapshot()
		if len(events) == 0 || events[len(events)-1].Kind != "runtime.sample" {
			t.Fatal("destruction preceded persisted snapshot")
		}
		var data struct {
			Boundary string `json:"boundary"`
		}
		if err := json.Unmarshal(events[len(events)-1].Data, &data); err != nil {
			t.Fatal(err)
		}
		if data.Boundary != "deletion" {
			t.Fatalf("pre-delete boundary = %q", data.Boundary)
		}
	}}
	runtime := testProviderRuntime(t, backend, provider, time.Second)
	runtime.SetUsageRecorder(recorder)
	if _, err := runtime.EnsureReady(context.Background(), instance); err != nil {
		t.Fatal(err)
	}
	if _, err := runtime.EnsureReady(context.Background(), instance); err != nil {
		t.Fatal(err)
	}
	if calls != 1 {
		t.Fatalf("warm request resampled runtime: %d samples", calls)
	}
	if err := runtime.Delete(context.Background(), instance); err != nil {
		t.Fatal(err)
	}
	boundaries := []string{}
	for _, event := range recorder.snapshot() {
		if event.Kind != "runtime.sample" {
			continue
		}
		var data struct {
			usage.Sample
			Boundary    string `json:"boundary"`
			OperationID string `json:"operation_id"`
		}
		if err := json.Unmarshal(event.Data, &data); err != nil {
			t.Fatal(err)
		}
		if event.IncarnationID != "physical-container" || event.WorkspaceID != instance.WorkspaceID || data.OperationID == "" {
			t.Fatalf("missing physical identity: %+v", event)
		}
		if data.MemoryLimitBytes == nil || *data.MemoryLimitBytes != limit || data.CPUUsageNS == nil || *data.CPUUsageNS != cpu || data.MemoryUsageBytes == nil || *data.MemoryUsageBytes != memory {
			t.Fatalf("resource facts lost: %s", event.Data)
		}
		if !data.ObservedAt.Equal(measurementAt) || data.MeasurementAt == nil || !data.MeasurementAt.Equal(measurementAt) {
			t.Fatalf("source timestamps lost: %s", event.Data)
		}
		boundaries = append(boundaries, data.Boundary)
	}
	if len(boundaries) != 2 || boundaries[0] != "activation" || boundaries[1] != "deletion" {
		t.Fatalf("boundaries = %v", boundaries)
	}
}

func TestFailedActivationSnapshotsBeforeCleanupWithIndependentContext(t *testing.T) {
	instance := dockerInstance()
	instance.WorkspaceID = "workspace"
	recorder := &usageRecorderStub{}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	backend := &boundaryBackendStub{
		runtimeBackendStub: &runtimeBackendStub{statuses: []statusReply{{status: "pending"}}},
		sample: func(ctx context.Context, id string) ([]usage.Sample, error) {
			if ctx.Err() != nil {
				t.Fatalf("cleanup inherited cancelled activation: %v", ctx.Err())
			}
			if _, ok := ctx.Deadline(); !ok {
				t.Fatal("cleanup sampling is unbounded")
			}
			return []usage.Sample{{Provider: "kubernetes", ResourceKind: "mcp_instance", ResourceID: id,
				WorkspaceID: instance.WorkspaceID, IncarnationID: "pending-pod-uid", State: "Pending",
				ObservedAt: time.Now().UTC(), MeasurementStatus: "unavailable", MeasurementReason: "metrics_missing"}}, nil
		},
	}
	provider := &boundaryProviderStub{beforeDelete: func() {
		events := recorder.snapshot()
		if len(events) != 1 || events[0].IncarnationID != "pending-pod-uid" {
			t.Fatalf("cleanup lost pending pod: %+v", events)
		}
		var data struct {
			Boundary string `json:"boundary"`
		}
		if err := json.Unmarshal(events[0].Data, &data); err != nil {
			t.Fatal(err)
		}
		if data.Boundary != "failed_start_cleanup" {
			t.Fatalf("cleanup boundary = %q", data.Boundary)
		}
	}}
	runtime := testProviderRuntime(t, backend, provider, time.Second)
	runtime.SetUsageRecorder(recorder)
	if _, err := runtime.EnsureReady(ctx, instance); !errors.Is(err, context.Canceled) {
		t.Fatalf("activation error = %v", err)
	}
	_, deletes := provider.counts()
	if deletes != 1 {
		t.Fatalf("cleanup deletions = %d", deletes)
	}
}

func TestRuntimeBoundaryUnavailableDoesNotInventUsageOrTrustForeignWorkspace(t *testing.T) {
	for _, scenario := range []string{"unsupported", "inventory_error", "missing", "foreign_workspace"} {
		t.Run(scenario, func(t *testing.T) {
			instance := dockerInstance()
			instance.WorkspaceID = "workspace"
			base := &runtimeBackendStub{statuses: []statusReply{{status: "running"}}}
			var backend backends.Backend = base
			if scenario != "unsupported" {
				backend = &boundaryBackendStub{runtimeBackendStub: base, sample: func(context.Context, string) ([]usage.Sample, error) {
					if scenario == "inventory_error" {
						return nil, errors.New("inventory unavailable")
					}
					if scenario == "missing" {
						return nil, nil
					}
					return []usage.Sample{{ResourceKind: "mcp_instance", ResourceID: instance.InstanceID, WorkspaceID: "another-tenant", IncarnationID: "foreign-container"}}, nil
				}}
			}
			recorder := &usageRecorderStub{}
			runtime := testProviderRuntime(t, backend, &runtimeProviderStub{}, time.Second)
			runtime.SetUsageRecorder(recorder)
			if err := runtime.Delete(context.Background(), instance); err != nil {
				t.Fatal(err)
			}
			events := recorder.snapshot()
			if len(events) != 2 || events[0].Kind != "runtime.sample" {
				t.Fatalf("missing unavailable fact: %+v", events)
			}
			var data usage.Sample
			if err := json.Unmarshal(events[0].Data, &data); err != nil {
				t.Fatal(err)
			}
			if data.MeasurementStatus != "unavailable" || data.MeasurementReason == "" || data.ObservedAt.IsZero() {
				t.Fatalf("missing unavailable reason: %s", events[0].Data)
			}
			if events[0].WorkspaceID != instance.WorkspaceID || data.WorkspaceID != instance.WorkspaceID || events[0].IncarnationID != "" || data.IncarnationID != "" {
				t.Fatalf("untrusted physical identity retained: %s", events[0].Data)
			}
			if data.CPUUsageNS != nil || data.MemoryUsageBytes != nil || data.CPUUsageNanocores != nil || data.MeasurementAt != nil {
				t.Fatalf("unavailable measurements fabricated: %s", events[0].Data)
			}
		})
	}
}

func TestRuntimeDoesNotDestroyUnrecordedBoundary(t *testing.T) {
	instance := dockerInstance()
	instance.WorkspaceID = "workspace"
	provider := &runtimeProviderStub{}
	runtime := testProviderRuntime(t, &runtimeBackendStub{}, provider, time.Second)
	recordErr := errors.New("persistence unavailable")
	runtime.SetUsageRecorder(boundaryRecorderFunc(func(ctx context.Context, event usage.Event) error {
		if _, ok := ctx.Deadline(); !ok {
			t.Fatal("record context is unbounded")
		}
		return recordErr
	}))
	if err := runtime.Delete(context.Background(), instance); !errors.Is(err, recordErr) {
		t.Fatalf("delete error = %v", err)
	}
	_, deletes := provider.counts()
	if deletes != 0 {
		t.Fatal("provider destruction preceded persisted boundary")
	}
}
