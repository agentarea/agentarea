package sandboxruntime

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/agentarea/mcp-manager/internal/usage"
	"github.com/google/uuid"
)

// SetUsageRecorder installs the trusted control-plane sink before serving work.
// Standalone runners use the Redis publisher, never a database connection.
func (m *Manager) SetUsageRecorder(recorder usage.Recorder) { m.usageRecorder = recorder }

func (m *Manager) recordAllocation(ctx context.Context, session *Session) error {
	if m.usageRecorder == nil {
		return nil
	}
	identity := sha256.Sum256([]byte(session.Provider + "\x00" + session.WorkspaceID + "\x00" + session.TaskID + "\x00" + session.ID))
	resources := make(map[string]string)
	for _, name := range []string{"cpu", "memory", "storage", "disk"} {
		if value := session.Data[name]; value != "" {
			resources[name] = value
		}
	}
	resourcesStatus := "unavailable"
	if len(resources) > 0 {
		resourcesStatus = "available"
	}
	timestampSource := session.Data["usage_timestamp_source"]
	if timestampSource == "" {
		timestampSource = "session_record"
	}
	data := map[string]any{
		"provider": session.Provider, "timestamp_source": timestampSource,
		"measurement_status": "lifecycle_only",
		"provider_resources": resources, "provider_resources_source": "session_allocation_metadata",
		"resources_status": resourcesStatus,
	}
	switch timestampSource {
	case "provider_started_at":
		data["started_at"] = session.CreatedAt
	case "provisioning_intent_started":
		data["provisioning_started_at"] = session.CreatedAt
	default:
		data["allocation_observed_at"] = session.CreatedAt
	}
	return m.recordUsage(ctx, session, "sandbox.allocated", "allocation-"+hex.EncodeToString(identity[:]), session.CreatedAt, data)
}

func (m *Manager) recordUsage(ctx context.Context, session *Session, kind, id string, observed time.Time, data map[string]any) error {
	if m.usageRecorder == nil {
		return nil
	}
	encoded, err := json.Marshal(data)
	if err != nil {
		return err
	}
	event := usage.Event{
		SchemaVersion: usage.SchemaVersion,
		ID:            id, Source: "sandbox-provider", Kind: kind,
		WorkspaceID: session.WorkspaceID, TaskID: session.TaskID,
		ResourceKind: "sandbox", ResourceID: session.Provider + "/" + session.ID,
		IncarnationID: session.ID, OccurredAt: observed, Data: encoded,
	}
	if err := m.usageRecorder.Record(ctx, event); err != nil {
		return fmt.Errorf("record sandbox usage %s %s for %s: %w", kind, id, session.ID, err)
	}
	return nil
}

func (m *Manager) deleteSession(ctx context.Context, session *Session, reason string) error {
	if m.usageRecorder == nil {
		err := m.provider.Delete(ctx, session)
		if errors.Is(err, ErrSessionNotFound) {
			return nil
		}
		return err
	}
	allocationErr := m.recordAllocation(ctx, session)
	attempt := uuid.NewString()
	requestErr := m.recordUsage(ctx, session, "sandbox.delete_requested", attempt+"-request", time.Now().UTC(), map[string]any{
		"provider": session.Provider, "reason": reason, "termination_confirmed": false,
	})
	deleteErr := m.provider.Delete(ctx, session)
	kind := "sandbox.delete_accepted"
	confirmed := false
	if errors.Is(deleteErr, ErrSessionNotFound) {
		kind = "sandbox.missing"
		confirmed = true
		deleteErr = nil
	} else if deleteErr != nil {
		kind = "sandbox.delete_failed"
	}
	outcomeCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), m.cleanupTTL)
	defer cancel()
	outcomeErr := m.recordUsage(outcomeCtx, session, kind, attempt+"-outcome", time.Now().UTC(), map[string]any{
		"provider": session.Provider, "reason": reason, "termination_confirmed": confirmed,
	})
	return errors.Join(deleteErr, allocationErr, requestErr, outcomeErr)
}

func (m *Manager) recordMissing(ctx context.Context, session *Session) error {
	return m.recordUsage(ctx, session, "sandbox.missing", uuid.NewString(), time.Now().UTC(), map[string]any{
		"provider": session.Provider, "termination_confirmed": true,
	})
}

func (m *Manager) recordProvisioning(ctx context.Context, intent ProvisioningIntent, phase string, requested, responded time.Time) error {
	if m.usageRecorder == nil {
		return nil
	}
	observed := responded
	if observed.IsZero() {
		observed = requested
	}
	data := map[string]any{
		"provider": intent.Provider, "operation_id": intent.ProvisioningID,
		"request_observed_at": requested, "allocation_visibility": "unavailable",
		"measurement_status": "unavailable",
		"measurement_reason": "provisioning_attempt_does_not_establish_physical_allocation",
	}
	if !responded.IsZero() {
		data["response_observed_at"] = responded
	}
	encoded, err := json.Marshal(data)
	if err != nil {
		return err
	}
	event := usage.Event{
		SchemaVersion: usage.SchemaVersion, Source: "sandbox-provider",
		ID: intent.ProvisioningID + "-" + phase, Kind: "sandbox.provisioning_" + phase,
		WorkspaceID: intent.WorkspaceID, TaskID: intent.TaskID,
		ResourceKind: "sandbox_provisioning", ResourceID: intent.WorkspaceID + "/" + intent.TaskID,
		OccurredAt: observed, Data: encoded,
	}
	recordCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), finalLeaseRenewTimeout)
	defer cancel()
	if err := m.usageRecorder.Record(recordCtx, event); err != nil {
		return fmt.Errorf("record sandbox provisioning usage %s %s: %w", phase, intent.ProvisioningID, err)
	}
	return nil
}
