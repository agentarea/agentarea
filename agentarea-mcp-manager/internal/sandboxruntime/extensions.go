package sandboxruntime

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
)

// createdAtSourceKey is the persisted session field naming how CreatedAt was
// established. Its value is part of the stored session format.
const createdAtSourceKey = "usage_timestamp_source"

// ErrLifecycleObservation marks a failed observer callback. Cleanup callers
// check it before treating a provider NotFound as an already-finished delete,
// so a failed observation is never normalized away with it.
var ErrLifecycleObservation = errors.New("lifecycle observation failed")

// SessionSnapshot is a value copy of the provider binding. It carries no
// provider handles or credentials; changing it never changes the session.
type SessionSnapshot struct {
	Provider    string
	ID          string
	WorkspaceID string
	TaskID      string
	CreatedAt   time.Time
	ExpiresAt   time.Time
	// CreatedAtSource says how CreatedAt was established; empty means the
	// session record itself.
	CreatedAtSource string
	// Resources holds only the allocation entries the provider reported
	// (cpu, memory, storage, disk).
	Resources map[string]string
}

type ProvisioningPhase string

const (
	ProvisioningStarted   ProvisioningPhase = "started"
	ProvisioningCompleted ProvisioningPhase = "completed"
	ProvisioningFailed    ProvisioningPhase = "failed"
)

// ProvisioningObservation records a provider request, not an allocation.
// RespondedAt is zero for the started phase.
type ProvisioningObservation struct {
	Intent      ProvisioningIntent
	Phase       ProvisioningPhase
	RequestedAt time.Time
	RespondedAt time.Time
}

type DeleteOutcome string

const (
	DeleteAccepted DeleteOutcome = "accepted"
	DeleteMissing  DeleteOutcome = "missing"
	DeleteFailed   DeleteOutcome = "failed"
)

type DeleteAttempt struct {
	Session     SessionSnapshot
	OperationID string
	Reason      string
	RequestedAt time.Time
}

type DeleteResult struct {
	Attempt     DeleteAttempt
	Outcome     DeleteOutcome
	RespondedAt time.Time
}

// LifecycleObserver sees external sandbox lifecycle points. The manager
// always performs the provider delete exactly once between BeforeDelete and
// AfterDelete, whatever BeforeDelete returns.
type LifecycleObserver interface {
	Allocation(context.Context, SessionSnapshot) error
	LeaseRenewed(ctx context.Context, session SessionSnapshot, state string, observedAt time.Time) error
	Missing(context.Context, SessionSnapshot) error
	Provisioning(context.Context, ProvisioningObservation) error
	BeforeDelete(context.Context, DeleteAttempt) error
	AfterDelete(context.Context, DeleteResult) error
}

// SetLifecycleObserver must be called before the manager serves work.
func (m *Manager) SetLifecycleObserver(observer LifecycleObserver) { m.observer = observer }

// AllocationInventory lists every live provider allocation, across
// workspaces, without renewing or creating one. The string names how the
// resource entries were obtained. It is not a tenant-facing listing.
type AllocationInventory interface {
	ListAllocations(context.Context) ([]SandboxStatus, string, error)
}

func (m *Manager) ListAllocations(ctx context.Context) ([]SandboxStatus, string, error) {
	inventory, ok := m.provider.(AllocationInventory)
	if !ok {
		return nil, "", fmt.Errorf("%w: %s provider has no allocation inventory", ErrInventoryUnavailable, m.provider.Name())
	}
	return inventory.ListAllocations(ctx)
}

var sessionResourceKeys = []string{"cpu", "memory", "storage", "disk"}

func sessionSnapshot(session *Session) SessionSnapshot {
	resources := make(map[string]string)
	for _, name := range sessionResourceKeys {
		if value := session.Data[name]; value != "" {
			resources[name] = value
		}
	}
	return SessionSnapshot{
		Provider: session.Provider, ID: session.ID, WorkspaceID: session.WorkspaceID, TaskID: session.TaskID,
		CreatedAt: session.CreatedAt, ExpiresAt: session.ExpiresAt,
		CreatedAtSource: session.Data[createdAtSourceKey], Resources: resources,
	}
}

func observationError(err error) error {
	if err == nil {
		return nil
	}
	return fmt.Errorf("%w: %w", ErrLifecycleObservation, err)
}

func (m *Manager) observeAllocation(ctx context.Context, session *Session) error {
	if m.observer == nil {
		return nil
	}
	return observationError(m.observer.Allocation(ctx, sessionSnapshot(session)))
}

func (m *Manager) observeLease(ctx context.Context, session *Session, state string, observedAt time.Time) error {
	if m.observer == nil {
		return nil
	}
	return observationError(m.observer.LeaseRenewed(ctx, sessionSnapshot(session), state, observedAt))
}

func (m *Manager) observeMissing(ctx context.Context, session *Session) error {
	if m.observer == nil {
		return nil
	}
	return observationError(m.observer.Missing(ctx, sessionSnapshot(session)))
}

func (m *Manager) observeProvisioning(ctx context.Context, intent ProvisioningIntent, phase ProvisioningPhase, requested, responded time.Time) error {
	if m.observer == nil {
		return nil
	}
	observeCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), finalLeaseRenewTimeout)
	defer cancel()
	return observationError(m.observer.Provisioning(observeCtx, ProvisioningObservation{
		Intent: intent, Phase: phase, RequestedAt: requested, RespondedAt: responded,
	}))
}

// deleteSession calls the provider exactly once. Observation failures are
// returned alongside the provider result, never instead of the delete.
func (m *Manager) deleteSession(ctx context.Context, session *Session, reason string) error {
	if m.observer == nil {
		err := m.provider.Delete(ctx, session)
		if errors.Is(err, ErrSessionNotFound) {
			return nil
		}
		return err
	}
	attempt := DeleteAttempt{
		Session: sessionSnapshot(session), OperationID: uuid.NewString(), Reason: reason, RequestedAt: time.Now().UTC(),
	}
	beforeErr := observationError(m.observer.BeforeDelete(ctx, attempt))
	providerErr := m.provider.Delete(ctx, session)
	result := DeleteResult{Attempt: attempt, Outcome: DeleteAccepted}
	switch {
	case errors.Is(providerErr, ErrSessionNotFound):
		result.Outcome, providerErr = DeleteMissing, nil
	case providerErr != nil:
		result.Outcome = DeleteFailed
	}
	result.RespondedAt = time.Now().UTC()
	afterCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), m.cleanupTTL)
	defer cancel()
	afterErr := observationError(m.observer.AfterDelete(afterCtx, result))
	return errors.Join(providerErr, beforeErr, afterErr)
}

// sessionAlreadyGone reports a provider NotFound that no observation failure
// accompanies; only then may cleanup treat the delete as done.
func sessionAlreadyGone(err error) bool {
	return errors.Is(err, ErrSessionNotFound) && !errors.Is(err, ErrLifecycleObservation)
}
