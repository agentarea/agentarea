package sandboxruntime

import (
	"context"
	"fmt"
	"time"

	usage "github.com/agentarea/agentarea/agentarea-go/internal/kernel/resourceusage"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/backends/workspace"
)

// AllocationSampler reads provider-owned inventory without renewing or
// creating a session. The tenant-scoped sandbox listing stays separately
// guarded; this inventory is never exposed over HTTP.
type AllocationSampler struct {
	inventory AllocationInventory
	provider  string
}

var _ usage.Sampler = (*AllocationSampler)(nil)

func NewAllocationSampler(inventory AllocationInventory, provider string) *AllocationSampler {
	return &AllocationSampler{inventory: inventory, provider: provider}
}

func (s *AllocationSampler) SampleUsage(ctx context.Context) ([]usage.Sample, error) {
	ctx, cancel := context.WithTimeout(ctx, usage.SampleTimeout)
	defer cancel()
	items, resourceSource, err := s.inventory.ListAllocations(ctx)
	if err != nil {
		return nil, fmt.Errorf("sample %s provider inventory: %w", s.provider, err)
	}
	observed := time.Now().UTC()
	result := make([]usage.Sample, 0, len(items))
	seen := make(map[string]struct{}, len(items))
	for _, item := range items {
		if item.ID == "" || item.Provider != s.provider {
			return nil, fmt.Errorf("provider usage inventory returned invalid session identity")
		}
		if _, exists := seen[item.ID]; exists {
			return nil, fmt.Errorf("provider usage inventory returned duplicate session %s", item.ID)
		}
		seen[item.ID] = struct{}{}
		if err := workspace.ValidateIdentifier("workspace_id", item.WorkspaceID); err != nil {
			return nil, fmt.Errorf("provider usage session %s: %w", item.ID, err)
		}
		if err := workspace.ValidateIdentifier("task_id", item.TaskID); err != nil {
			return nil, fmt.Errorf("provider usage session %s: %w", item.ID, err)
		}
		sample := usage.Sample{
			Provider: item.Provider, ResourceKind: "sandbox", ResourceID: item.Provider + "/" + item.ID,
			IncarnationID: item.ID, WorkspaceID: item.WorkspaceID, TaskID: item.TaskID,
			State: item.State, ObservedAt: observed, ExpiresAt: item.ExpiresAt,
			ProviderResources: item.Resources, ProviderResourcesSource: resourceSource,
			MeasurementStatus: "unavailable", MeasurementReason: "provider inventory does not expose actual CPU or memory usage; expires_at is an intended lease boundary",
		}
		if !item.CreatedAt.IsZero() {
			started := item.CreatedAt
			sample.StartedAt = &started
		}
		result = append(result, sample)
	}
	return result, nil
}
