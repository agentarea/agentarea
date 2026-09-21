package sandboxruntime

import (
	"context"
	"fmt"
	"time"

	"github.com/agentarea/mcp-manager/internal/usage"
	"github.com/agentarea/mcp-manager/internal/workspace"
)

// SampleUsage reads provider-owned inventory without renewing or creating a
// session. Public workspace-scoped inventory remains separately guarded.
func (m *Manager) SampleUsage(ctx context.Context) ([]usage.Sample, error) {
	inventory, ok := m.provider.(interface {
		listUsage(context.Context) ([]SandboxStatus, string, error)
	})
	if !ok {
		return nil, fmt.Errorf("%s provider usage inventory is unavailable", m.provider.Name())
	}
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	items, resourceSource, err := inventory.listUsage(ctx)
	if err != nil {
		return nil, fmt.Errorf("sample %s provider inventory: %w", m.provider.Name(), err)
	}
	observed := time.Now().UTC()
	result := make([]usage.Sample, 0, len(items))
	seen := make(map[string]struct{}, len(items))
	for _, item := range items {
		if item.ID == "" || item.Provider != m.provider.Name() {
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
