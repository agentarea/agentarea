package mcpgateway

import (
	"context"
	"time"
)

// Transition names a committed control-plane lifecycle change. Consumers
// receive only these values; an unknown value is a programming error on their
// side, not a new kind of fact.
type Transition string

const (
	TransitionStarting         Transition = "starting"
	TransitionReady            Transition = "ready"
	TransitionFailed           Transition = "failed"
	TransitionRetiring         Transition = "retiring"
	TransitionRetirementFailed Transition = "retirement_failed"
	TransitionRetired          Transition = "retired"
)

// LifecycleChange is the runtime row as the owning transaction will commit it.
// A generation is a control-plane activation, not a physical pod or container.
type LifecycleChange struct {
	InstanceID  string
	WorkspaceID string
	Generation  int64
	State       string
	Transition  Transition
	Reason      string
	UpdatedAt   time.Time
}

// RequestStarted describes an admitted, authenticated request before the
// gateway starts or proxies to its workload. MCPMethod and MCPName are nil when
// the request carried no routing header, as 2025-era clients do not.
type RequestStarted struct {
	RequestID   string
	InstanceID  string
	WorkspaceID string
	Method      string
	MCPMethod   *string
	MCPName     *string
	StartedAt   time.Time
}

// RequestCompleted is reported once for every request whose start was
// accepted. EndedAt precedes lease cleanup; StatusCode is the final status
// written, or zero when nothing was written.
type RequestCompleted struct {
	RequestStarted
	EndedAt    time.Time
	StatusCode int
	Canceled   bool
}

// RequestObserver sees request boundaries without the request or response.
// A Started error makes the gateway refuse the request; a Completed error is
// logged because the response has already been sent.
type RequestObserver interface {
	Started(context.Context, RequestStarted) error
	Completed(context.Context, RequestCompleted) error
}

// SetRequestObserver must be called before serving requests.
func (g *Gateway) SetRequestObserver(observer RequestObserver) { g.requests = observer }

type ResourceRef struct {
	InstanceID  string
	WorkspaceID string
}

type OperationKind string

const (
	OperationCreation OperationKind = "creation"
	OperationDeletion OperationKind = "deletion"
)

type OperationPhase string

const (
	OperationStarted   OperationPhase = "started"
	OperationCompleted OperationPhase = "completed"
	OperationFailed    OperationPhase = "failed"
)

// RuntimeBoundary marks a moment when a short-lived workload may disappear
// before any periodic observation reaches it.
type RuntimeBoundary string

const (
	BoundaryActivation         RuntimeBoundary = "activation"
	BoundaryCreationFailed     RuntimeBoundary = "creation_failed"
	BoundaryDeletion           RuntimeBoundary = "deletion"
	BoundaryFailedStartCleanup RuntimeBoundary = "failed_start_cleanup"
)

type RuntimeOperation struct {
	Resource    ResourceRef
	OperationID string
	Operation   OperationKind
	Phase       OperationPhase
	ObservedAt  time.Time
}

type BoundaryObservation struct {
	Resource    ResourceRef
	OperationID string
	Boundary    RuntimeBoundary
}

// RuntimeObserver sees provider operations. Errors keep the existing
// fail-closed order: a failed creation start aborts the start, a failed
// activation observation cleans up the new workload, and a failed pre-delete
// observation leaves the workload in place.
type RuntimeObserver interface {
	Operation(context.Context, RuntimeOperation) error
	Boundary(context.Context, BoundaryObservation) error
}

// SetRuntimeObserver must be called before the runtime serves requests.
func (r *ProviderRuntime) SetRuntimeObserver(observer RuntimeObserver) { r.observer = observer }
