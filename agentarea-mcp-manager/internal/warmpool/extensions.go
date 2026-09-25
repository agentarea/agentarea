package warmpool

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	corev1 "k8s.io/api/core/v1"
	k8serrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// ErrLifecycleObservation marks a failed observer callback. Cleanup callers
// check it before treating NotFound or Conflict as an already-finished delete.
var ErrLifecycleObservation = errors.New("lifecycle observation failed")

// ContainerAllocation is one container's declared resource requirements.
type ContainerAllocation struct {
	Name      string
	Resources corev1.ResourceRequirements
}

// TaskPodSnapshot copies the operational metadata and resource requirements of
// a task pod. It carries no environment, commands or secrets; the timestamps
// keep the annotation text exactly as stored.
type TaskPodSnapshot struct {
	Namespace      string
	Name           string
	UID            string
	WorkspaceID    string
	TaskID         string
	State          string
	AssignedAt     string
	LeaseUntil     string
	CleanupAt      string
	Containers     []ContainerAllocation
	InitContainers []ContainerAllocation
	Overhead       corev1.ResourceList
}

type DeleteOutcome string

const (
	DeleteAccepted DeleteOutcome = "accepted"
	DeleteMissing  DeleteOutcome = "missing"
	DeleteFailed   DeleteOutcome = "failed"
)

type DeleteAttempt struct {
	Pod         TaskPodSnapshot
	OperationID string
	Reason      string
	RequestedAt time.Time
}

type DeleteResult struct {
	Attempt     DeleteAttempt
	Outcome     DeleteOutcome
	RespondedAt time.Time
}

// LifecycleObserver sees task-pod lifecycle points. The client always sends
// exactly one Kubernetes delete between BeforeDelete and AfterDelete, whatever
// BeforeDelete returns.
type LifecycleObserver interface {
	Allocation(context.Context, TaskPodSnapshot) error
	Lease(context.Context, TaskPodSnapshot) error
	BeforeDelete(context.Context, DeleteAttempt) error
	AfterDelete(context.Context, DeleteResult) error
}

// SetLifecycleObserver must be called before the client serves work.
func (c *Client) SetLifecycleObserver(observer LifecycleObserver) { c.observer = observer }

func containerAllocations(containers []corev1.Container) []ContainerAllocation {
	allocations := make([]ContainerAllocation, 0, len(containers))
	for _, container := range containers {
		allocations = append(allocations, ContainerAllocation{Name: container.Name, Resources: *container.Resources.DeepCopy()})
	}
	return allocations
}

func taskPodSnapshot(pod *corev1.Pod) TaskPodSnapshot {
	return TaskPodSnapshot{
		Namespace: pod.Namespace, Name: pod.Name, UID: string(pod.UID),
		WorkspaceID: pod.Annotations[annotationWorkspaceID], TaskID: pod.Annotations[annotationTaskID],
		State:      pod.Labels[labelStatus],
		AssignedAt: pod.Annotations[annotationTaskAssignedAt], LeaseUntil: pod.Annotations[annotationTaskLeaseUntil],
		CleanupAt:  pod.Annotations[annotationTaskCleanupAt],
		Containers: containerAllocations(pod.Spec.Containers), InitContainers: containerAllocations(pod.Spec.InitContainers),
		Overhead: pod.Spec.Overhead.DeepCopy(),
	}
}

func observationError(err error) error {
	if err == nil {
		return nil
	}
	return fmt.Errorf("%w: %w", ErrLifecycleObservation, err)
}

func (c *Client) observeAllocation(ctx context.Context, pod *corev1.Pod) error {
	if c.observer == nil {
		return nil
	}
	return observationError(c.observer.Allocation(ctx, taskPodSnapshot(pod)))
}

func (c *Client) observeLease(ctx context.Context, pod *corev1.Pod) error {
	if c.observer == nil {
		return nil
	}
	return observationError(c.observer.Lease(ctx, taskPodSnapshot(pod)))
}

// deleteTaskPod sends exactly one delete with the caller's preconditions.
// Observation failures are returned with the delete result, never instead of
// the delete, and carry ErrLifecycleObservation so callers do not normalize
// them away together with NotFound or Conflict.
func (c *Client) deleteTaskPod(ctx context.Context, pod *corev1.Pod, options metav1.DeleteOptions, reason string) error {
	if c.observer == nil {
		return c.client.CoreV1().Pods(c.namespace).Delete(ctx, pod.Name, options)
	}
	attempt := DeleteAttempt{Pod: taskPodSnapshot(pod), OperationID: uuid.NewString(), Reason: reason, RequestedAt: time.Now().UTC()}
	beforeErr := observationError(c.observer.BeforeDelete(ctx, attempt))
	deleteErr := c.client.CoreV1().Pods(c.namespace).Delete(ctx, pod.Name, options)
	result := DeleteResult{Attempt: attempt, Outcome: DeleteAccepted}
	switch {
	case k8serrors.IsNotFound(deleteErr):
		result.Outcome = DeleteMissing
	case deleteErr != nil:
		result.Outcome = DeleteFailed
	}
	result.RespondedAt = time.Now().UTC()
	afterCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 15*time.Second)
	defer cancel()
	afterErr := observationError(c.observer.AfterDelete(afterCtx, result))
	return errors.Join(deleteErr, beforeErr, afterErr)
}

// podAlreadyGone reports a NotFound (or, where allowed, Conflict) delete result
// that no observation failure accompanies.
func podAlreadyGone(err error, conflictToo bool) bool {
	if errors.Is(err, ErrLifecycleObservation) {
		return false
	}
	return k8serrors.IsNotFound(err) || (conflictToo && k8serrors.IsConflict(err))
}
