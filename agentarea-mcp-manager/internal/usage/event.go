// Package usage records resource facts independently of pricing and payments.
package usage

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"
)

// SchemaVersion identifies the interpretation contract for newly emitted facts.
const SchemaVersion = 1

// Event identifies an immutable observation. Source and ID together identify a
// delivery across retries; resource identity survives deletion of the workload.
type Event struct {
	SchemaVersion int             `json:"schema_version"`
	ID            string          `json:"id"`
	Source        string          `json:"source"`
	Kind          string          `json:"kind"`
	WorkspaceID   string          `json:"workspace_id"`
	ResourceKind  string          `json:"resource_kind"`
	ResourceID    string          `json:"resource_id"`
	IncarnationID string          `json:"incarnation_id,omitempty"`
	TaskID        string          `json:"task_id,omitempty"`
	OccurredAt    time.Time       `json:"occurred_at"`
	Data          json.RawMessage `json:"data"`
}

type Recorder interface {
	Record(context.Context, Event) error
}

func (e Event) Validate() error {
	if e.SchemaVersion != SchemaVersion {
		return fmt.Errorf("unsupported usage schema_version %d; expected %d", e.SchemaVersion, SchemaVersion)
	}
	for name, value := range map[string]string{"id": e.ID, "source": e.Source, "kind": e.Kind, "resource_kind": e.ResourceKind, "resource_id": e.ResourceID} {
		if strings.TrimSpace(value) == "" || len(value) > 512 {
			return fmt.Errorf("usage event %s must contain 1..512 characters", name)
		}
	}
	if e.WorkspaceID == "" && e.ResourceKind != "platform_runtime" {
		return fmt.Errorf("usage event workspace_id is required for tenant resources")
	}
	if e.OccurredAt.IsZero() {
		return fmt.Errorf("usage event occurred_at is required")
	}
	data := bytes.TrimSpace(e.Data)
	if !json.Valid(data) || len(data) == 0 || data[0] != '{' {
		return fmt.Errorf("usage event data must be a JSON object")
	}
	return nil
}

// Sample preserves source units and distinguishes a CPU rate from a cumulative
// CPU counter. Missing measurements stay absent; they never become zero usage.
type Sample struct {
	Provider                string            `json:"provider"`
	ResourceKind            string            `json:"resource_kind"`
	ResourceID              string            `json:"resource_id"`
	IncarnationID           string            `json:"incarnation_id"`
	WorkspaceID             string            `json:"workspace_id"`
	TaskID                  string            `json:"task_id,omitempty"`
	State                   string            `json:"state"`
	ObservedAt              time.Time         `json:"observed_at"`
	MeasurementAt           *time.Time        `json:"measurement_at,omitempty"`
	StartedAt               *time.Time        `json:"started_at,omitempty"`
	CPURequestNanocores     *int64            `json:"cpu_request_nanocores,omitempty"`
	CPULimitNanocores       *int64            `json:"cpu_limit_nanocores,omitempty"`
	CPUQuotaUS              *int64            `json:"cpu_quota_us,omitempty"`
	CPUPeriodUS             *int64            `json:"cpu_period_us,omitempty"`
	MemoryRequestBytes      *int64            `json:"memory_request_bytes,omitempty"`
	MemoryLimitBytes        *int64            `json:"memory_limit_bytes,omitempty"`
	CPUUsageNS              *uint64           `json:"cpu_usage_ns,omitempty"`
	CPUUsageNanocores       *int64            `json:"cpu_usage_nanocores,omitempty"`
	CPUWindowNS             *int64            `json:"cpu_window_ns,omitempty"`
	MemoryUsageBytes        *uint64           `json:"memory_usage_bytes,omitempty"`
	MemoryMetric            string            `json:"memory_metric,omitempty"`
	MeasurementStatus       string            `json:"measurement_status"`
	MeasurementReason       string            `json:"measurement_reason,omitempty"`
	ProviderResources       map[string]string `json:"provider_resources,omitempty"`
	ProviderResourcesSource string            `json:"provider_resources_source,omitempty"`
	ExpiresAt               *time.Time        `json:"expires_at,omitempty"`
}

// Sampler is implemented at the runtime boundary, including remote data planes.
// A failed inventory must return an error, not an empty successful inventory.
type Sampler interface {
	SampleUsage(context.Context) ([]Sample, error)
}

// ResourceSampler observes one logical MCP instance, including every current
// physical incarnation. A missing resource returns an empty inventory.
type ResourceSampler interface {
	SampleResourceUsage(context.Context, string) ([]Sample, error)
}
