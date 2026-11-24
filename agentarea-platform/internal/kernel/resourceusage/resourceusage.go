// Package resourceusage is what a runtime observes of the resources it runs:
// samples in source units, read at the runtime boundary. It carries no prices.
package resourceusage

import (
	"context"
	"time"
)

// Sample preserves source units and distinguishes a CPU rate from a cumulative
// CPU counter. A missing measurement stays absent; it never becomes zero usage.
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

// Sampler reads a runtime's whole inventory. A failed inventory is an error,
// never an empty one.
type Sampler interface {
	SampleUsage(ctx context.Context) ([]Sample, error)
}

// ResourceSampler observes one logical MCP instance, including every physical
// incarnation; a missing one is an empty inventory.
type ResourceSampler interface {
	SampleResourceUsage(ctx context.Context, resourceID string) ([]Sample, error)
}

// RuntimeSampler is a workload backend's sampler: both.
type RuntimeSampler interface {
	Sampler
	ResourceSampler
}

// SampleTimeout bounds one inventory; SourceTimeout one metrics read inside it.
const (
	SampleTimeout = 30 * time.Second
	SourceTimeout = 5 * time.Second
)
