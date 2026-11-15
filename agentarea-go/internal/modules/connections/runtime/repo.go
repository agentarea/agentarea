package runtime

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/gateway"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/runtime/store"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/runtime/workload"
)

const (
	lockWait         = 2 * time.Second
	lockPollInterval = 25 * time.Millisecond
	// StatusChanged is the outbox event every lifecycle transition emits
	// (the manager's MCPServerInstanceStatusChanged and MCPServerInstanceError
	// and Python's never-published MCPServerInstanceStarted/Stopped, as one).
	StatusChanged = "MCPServerInstanceStatusChanged"
	// EventPrincipal is the outbox row's created_by for runtime transitions.
	EventPrincipal = "system:mcp-runtime"
)

func lockKey(instanceID string) db.LockKey { return db.TextKey(instanceID) }

// withInstanceLock runs fn holding the instance's lifecycle lock, a session
// advisory lock on hashtextextended(id, 0) as the manager took it, polled for
// two seconds; ErrStartInProgress when another caller keeps it.
func (r *Runtime) withInstanceLock(ctx context.Context, instanceID string, fn func(ctx context.Context) error) error {
	deadline := time.Now().Add(lockWait)
	for {
		ok, err := r.d.DB.TrySessionLock(ctx, lockKey(instanceID), func(ctx context.Context, _ db.Querier) error {
			return fn(ctx)
		})
		if ok {
			return err
		}
		if err != nil {
			return fmt.Errorf("lock MCP instance lifecycle: %w", err)
		}
		if !time.Now().Before(deadline) {
			return gateway.ErrStartInProgress
		}
		t := time.NewTimer(lockPollInterval)
		select {
		case <-ctx.Done():
			t.Stop()
			return ctx.Err()
		case <-t.C:
		}
	}
}

func parseID(instanceID string) (uuid.UUID, error) {
	id, err := uuid.Parse(instanceID)
	if err != nil {
		return uuid.UUID{}, gateway.ErrInstanceNotFound
	}
	return id, nil
}

// beforeCommit reads the row the transition left, hands it to the
// participant and emits StatusChanged, all in the transition's transaction.
func (r *Runtime) beforeCommit(ctx context.Context, q db.Querier, id uuid.UUID, t Transition, reason, lastError string) error {
	row, err := store.New(q).LifecycleRow(ctx, id)
	if err != nil {
		return fmt.Errorf("read MCP lifecycle row: %w", err)
	}
	change := LifecycleChange{InstanceID: id.String(), WorkspaceID: row.WorkspaceID, Generation: row.Generation,
		State: row.State, Transition: t, Reason: reason, UpdatedAt: row.UpdatedAt.Time}
	if r.d.Participant != nil {
		if err := r.d.Participant(ctx, q, change); err != nil {
			return fmt.Errorf("MCP lifecycle %s participant for instance %s: %w", t, change.InstanceID, err)
		}
	}
	ws, err := scope.NewWorkspace(change.WorkspaceID, "")
	if err != nil {
		return err
	}
	data := map[string]any{
		"instance_id": change.InstanceID, "workspace_id": change.WorkspaceID, "generation": change.Generation,
		"state": change.State, "transition": string(t), "reason": reason,
	}
	if lastError != "" {
		data["error"] = lastError
	}
	return events.Publish(ctx, db.NewTxSession(ws, q), EventPrincipal, events.NewEnvelope(StatusChanged, data))
}

func (r *Runtime) markStarting(ctx context.Context, id uuid.UUID) error {
	return r.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		n, err := store.New(q).MarkStarting(ctx, id)
		if err != nil || n == 0 {
			return err
		}
		return r.beforeCommit(ctx, q, id, TransitionStarting, ReasonDemand, "")
	})
}

func (r *Runtime) markFailed(ctx context.Context, id uuid.UUID, cause error) error {
	return r.setState(ctx, id, "failed", TransitionFailed, ReasonActivation, cause.Error())
}

func (r *Runtime) markReadyAndBeginRequest(ctx context.Context, id, requestID uuid.UUID) error {
	return r.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		s := store.New(q)
		previous, err := s.StateForUpdate(ctx, id)
		if err != nil {
			return err
		}
		n, err := s.SetReady(ctx, id)
		if err != nil {
			return err
		}
		if n != 1 {
			return errors.New("MCP runtime ownership was lost before request admission")
		}
		if err := s.BeginLease(ctx, store.BeginLeaseParams{RequestID: requestID, InstanceID: id, TtlSeconds: r.d.Config.LeaseTTL.Seconds()}); err != nil {
			return err
		}
		if previous != "ready" {
			return r.beforeCommit(ctx, q, id, TransitionReady, ReasonDemand, "")
		}
		return nil
	})
}

func (r *Runtime) heartbeat(ctx context.Context, requestID uuid.UUID) error {
	return r.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		n, err := store.New(q).HeartbeatLease(ctx, store.HeartbeatLeaseParams{RequestID: requestID, TtlSeconds: r.d.Config.LeaseTTL.Seconds()})
		if err != nil {
			return err
		}
		if n != 1 {
			return errors.New("MCP request lease ownership was lost")
		}
		return nil
	})
}

func (r *Runtime) finishRequest(ctx context.Context, id, requestID uuid.UUID) error {
	return r.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		s := store.New(q)
		n, err := s.FinishLease(ctx, store.FinishLeaseParams{RequestID: requestID, InstanceID: id})
		if err != nil {
			return err
		}
		if n != 1 {
			return errors.New("MCP request lease ownership was lost before finalization")
		}
		return s.TouchUsed(ctx, id)
	})
}

func (r *Runtime) setState(ctx context.Context, id uuid.UUID, state string, t Transition, reason, lastError string) error {
	return r.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		if err := store.New(q).SetState(ctx, store.SetStateParams{InstanceID: id, State: state, LastError: lastError}); err != nil {
			return err
		}
		return r.beforeCommit(ctx, q, id, t, reason, lastError)
	})
}

func (r *Runtime) idleCandidates(ctx context.Context) ([]uuid.UUID, error) {
	var ids []uuid.UUID
	err := r.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		s := store.New(q)
		if err := s.DeleteExpiredLeases(ctx); err != nil {
			return err
		}
		var err error
		ids, err = s.IdleCandidates(ctx, r.d.Config.IdleTimeout.Seconds())
		return err
	})
	return ids, err
}

// readQ reads lifecycle rows from the primary: a replica's lag would let a
// decision under the instance lock see a state already gone.
func (r *Runtime) readQ(ctx context.Context, fn func(s *store.Queries) error) error {
	return r.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error { return fn(store.New(q)) })
}

// reapIfIdle retires an idle workload under the instance lock; a removal
// that fails restores the state it found.
func (r *Runtime) reapIfIdle(ctx context.Context, id uuid.UUID) (bool, error) {
	removed := false
	err := r.withInstanceLock(ctx, id.String(), func(ctx context.Context) error {
		var eligible bool
		var previous string
		err := r.readQ(ctx, func(s *store.Queries) error {
			var err error
			if eligible, err = s.IdleEligible(ctx, store.IdleEligibleParams{InstanceID: id, IdleSeconds: r.d.Config.IdleTimeout.Seconds()}); err != nil || !eligible {
				return err
			}
			previous, err = s.InstanceState(ctx, id)
			return err
		})
		if err != nil || !eligible {
			return err
		}
		inst, err := r.loadContainer(ctx, id.String())
		if err != nil {
			return err
		}
		if err := r.setState(ctx, id, "reaping", TransitionRetiring, ReasonIdle, ""); err != nil {
			return err
		}
		if err := r.remove(ctx, inst); err != nil {
			return errors.Join(err, r.setState(ctx, id, previous, TransitionRetirementFailed, ReasonIdle, err.Error()))
		}
		if err := r.setState(ctx, id, "dormant", TransitionRetired, ReasonIdle, ""); err != nil {
			return err
		}
		removed = true
		return nil
	})
	return removed, err
}

// retireForDeletion stops the workload of an instance about to change or go;
// ErrInstanceBusy while a live lease holds it.
func (r *Runtime) retireForDeletion(ctx context.Context, instanceID string) error {
	id, err := parseID(instanceID)
	if err != nil {
		return err
	}
	return r.withInstanceLock(ctx, instanceID, func(ctx context.Context) error {
		l, err := r.load(ctx, instanceID)
		if errors.Is(err, gateway.ErrInstanceNotFound) {
			// The row is gone (its runtime rows with it); the workload may not be.
			if err := r.d.Backend.Delete(ctx, instanceID); err != nil && !errors.Is(err, workload.ErrNotFound) {
				return fmt.Errorf("delete MCP workload of a removed instance: %w", err)
			}
			r.clearFailure(instanceID)
			return nil
		}
		if err != nil {
			return err
		}
		if l.container == nil {
			return nil
		}
		inst := l.container
		var active bool
		if err := r.readQ(ctx, func(s *store.Queries) error {
			var err error
			active, err = s.LiveLeaseExists(ctx, id)
			return err
		}); err != nil {
			return err
		}
		if active {
			return gateway.ErrInstanceBusy
		}
		if err := r.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
			if err := store.New(q).BeginRetirement(ctx, id); err != nil {
				return err
			}
			return r.beforeCommit(ctx, q, id, TransitionRetiring, ReasonDeletion, "")
		}); err != nil {
			return err
		}
		if err := r.remove(ctx, inst); err != nil {
			return errors.Join(err, r.setState(ctx, id, "failed", TransitionRetirementFailed, ReasonDeletion, err.Error()))
		}
		return r.setState(ctx, id, "dormant", TransitionRetired, ReasonDeletion, "")
	})
}

func (r *Runtime) countByState(ctx context.Context) (map[string]int64, error) {
	out := map[string]int64{}
	err := r.readQ(ctx, func(s *store.Queries) error {
		rows, err := s.CountByState(ctx)
		for _, row := range rows {
			out[row.State] = row.N
		}
		return err
	})
	return out, err
}
