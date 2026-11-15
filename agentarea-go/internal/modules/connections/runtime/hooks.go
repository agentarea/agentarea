package runtime

import (
	"context"
	"errors"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/runtime/workload"
)

// Transition is a lifecycle state change of an instance's workload.
type Transition string

const (
	TransitionStarting         Transition = "starting"
	TransitionReady            Transition = "ready"
	TransitionFailed           Transition = "failed"
	TransitionRetiring         Transition = "retiring"
	TransitionRetirementFailed Transition = "retirement_failed"
	TransitionRetired          Transition = "retired"
)

// Reasons a transition happens.
const (
	ReasonDemand     = "demand"
	ReasonActivation = "activation"
	ReasonIdle       = "idle"
	ReasonDeletion   = "deletion"
)

// LifecycleChange is the row a transition left, read inside its transaction.
type LifecycleChange struct {
	InstanceID  string
	WorkspaceID string
	Generation  int64
	State       string
	Transition  Transition
	Reason      string
	UpdatedAt   time.Time
}

// LifecycleParticipant runs inside every transition's transaction; an error
// rolls the transition back.
type LifecycleParticipant func(ctx context.Context, q db.Querier, c LifecycleChange) error

// SpecHook rewrites a workload spec before it starts; an error refuses the start.
type SpecHook func(ctx context.Context, instanceID, workspaceID string, spec *workload.Spec) error

// OperationKind is what a runtime operation does to a workload.
type OperationKind string

const (
	OperationCreation OperationKind = "creation"
	OperationDeletion OperationKind = "deletion"
)

// OperationPhase is where an operation stands.
type OperationPhase string

const (
	OperationStarted   OperationPhase = "started"
	OperationCompleted OperationPhase = "completed"
	OperationFailed    OperationPhase = "failed"
)

// Boundary is a point a workload's existence changes at.
type Boundary string

const (
	BoundaryActivation         Boundary = "activation"
	BoundaryCreationFailed     Boundary = "creation_failed"
	BoundaryDeletion           Boundary = "deletion"
	BoundaryFailedStartCleanup Boundary = "failed_start_cleanup"
)

// Operation is one phase of a creation or deletion.
type Operation struct {
	InstanceID  string
	WorkspaceID string
	OperationID string
	Kind        OperationKind
	Phase       OperationPhase
	ObservedAt  time.Time
}

// BoundaryObservation is a boundary an operation crossed.
type BoundaryObservation struct {
	InstanceID  string
	WorkspaceID string
	OperationID string
	Boundary    Boundary
}

// Observer sees workload operations. An error on a started creation refuses
// the start; other errors are reported with the operation's own.
type Observer interface {
	Operation(ctx context.Context, o Operation) error
	Boundary(ctx context.Context, b BoundaryObservation) error
}

type observers []Observer

func (o observers) Operation(ctx context.Context, op Operation) error {
	errs := make([]error, 0, len(o))
	for _, obs := range o {
		err := obs.Operation(ctx, op)
		if err != nil && op.Phase == OperationStarted {
			return err
		}
		errs = append(errs, err)
	}
	return errors.Join(errs...)
}

func (o observers) Boundary(ctx context.Context, b BoundaryObservation) error {
	errs := make([]error, 0, len(o))
	for _, obs := range o {
		errs = append(errs, obs.Boundary(ctx, b))
	}
	return errors.Join(errs...)
}
