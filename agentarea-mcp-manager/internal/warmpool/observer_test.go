package warmpool

import (
	"context"
	"errors"
	"testing"
	"time"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/kubernetes/fake"
	k8stesting "k8s.io/client-go/testing"
)

type podObserverStub struct {
	allocations []TaskPodSnapshot
	leases      []TaskPodSnapshot
	deletes     []DeleteResult
	beforeErr   error
}

func (o *podObserverStub) Allocation(_ context.Context, pod TaskPodSnapshot) error {
	o.allocations = append(o.allocations, pod)
	return nil
}

func (o *podObserverStub) Lease(_ context.Context, pod TaskPodSnapshot) error {
	o.leases = append(o.leases, pod)
	return nil
}

func (o *podObserverStub) BeforeDelete(_ context.Context, attempt DeleteAttempt) error {
	for i := range attempt.Pod.Containers {
		attempt.Pod.Containers[i].Resources.Limits[corev1.ResourceCPU] = resource.MustParse("64")
	}
	return o.beforeErr
}

func (o *podObserverStub) AfterDelete(ctx context.Context, result DeleteResult) error {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	o.deletes = append(o.deletes, result)
	return nil
}

func TestObserverLeaseSnapshotsFollowPodIncarnation(t *testing.T) {
	pod := taskPod("sandbox-1", "task-1", statusAssigned)
	pod.UID = types.UID("first")
	pod.Annotations[annotationTaskAssignedAt] = time.Now().UTC().Format(time.RFC3339)
	clientset := fake.NewSimpleClientset(pod)
	client := NewClient(clientset, "test", time.Hour)
	observer := &podObserverStub{}
	client.SetLifecycleObserver(observer)
	ctx := context.Background()
	for range 2 {
		if err := client.TouchTaskPod(ctx, pod, time.Hour); err != nil {
			t.Fatal(err)
		}
	}
	if err := clientset.CoreV1().Pods("test").Delete(ctx, pod.Name, metav1.DeleteOptions{}); err != nil {
		t.Fatal(err)
	}
	pod.UID = types.UID("replacement")
	if _, err := clientset.CoreV1().Pods("test").Create(ctx, pod, metav1.CreateOptions{}); err != nil {
		t.Fatal(err)
	}
	if err := client.TouchTaskPod(ctx, pod, time.Hour); err != nil {
		t.Fatal(err)
	}
	uids := map[string]int{}
	for _, lease := range observer.leases {
		if lease.WorkspaceID != "workspace-1" || lease.TaskID != "task-1" || lease.LeaseUntil == "" {
			t.Fatalf("lease snapshot lost operational metadata: %+v", lease)
		}
		uids[lease.UID]++
	}
	if len(uids) != 2 || uids["first"] != 2 || uids["replacement"] != 1 {
		t.Fatalf("lease incarnations = %v", uids)
	}
}

func TestObserverFailedPodDeleteIsNotReportedAccepted(t *testing.T) {
	pod := taskPod("sandbox-1", "task-1", statusAssigned)
	pod.UID = types.UID("first")
	clientset := fake.NewSimpleClientset(pod)
	clientset.PrependReactor("delete", "pods", func(k8stesting.Action) (bool, runtime.Object, error) {
		return true, nil, errors.New("API unavailable")
	})
	client := NewClient(clientset, "test", time.Hour)
	observer := &podObserverStub{}
	client.SetLifecycleObserver(observer)
	if err := client.RetirePodForTask(context.Background(), "workspace-1", "task-1", 0); err == nil {
		t.Fatal("expected delete failure")
	}
	if len(observer.deletes) != 1 || observer.deletes[0].Outcome != DeleteFailed || observer.deletes[0].Attempt.Reason != "retirement" {
		t.Fatalf("failed delete outcome = %+v", observer.deletes)
	}
}

func TestObserverFailureBeforePodDeleteStillDeletesOnceAndIsNotNormalized(t *testing.T) {
	pod := taskPod("sandbox-1", "task-1", statusAssigned)
	pod.UID = types.UID("first")
	pod.Spec.Containers = []corev1.Container{{Name: "executor", Resources: corev1.ResourceRequirements{
		Limits: corev1.ResourceList{corev1.ResourceCPU: resource.MustParse("1")},
	}}}
	clientset := fake.NewSimpleClientset()
	deletes := 0
	clientset.PrependReactor("delete", "pods", func(k8stesting.Action) (bool, runtime.Object, error) {
		deletes++
		return false, nil, nil
	})
	client := NewClient(clientset, "test", time.Hour)
	observer := &podObserverStub{beforeErr: errors.New("ledger unavailable")}
	client.SetLifecycleObserver(observer)
	err := client.DeleteExactPod(context.Background(), pod)
	if err == nil || !errors.Is(err, ErrLifecycleObservation) {
		t.Fatalf("NotFound hid an observation failure: %v", err)
	}
	if deletes != 1 {
		t.Fatalf("Kubernetes deletes = %d, want exactly 1", deletes)
	}
	if len(observer.deletes) != 1 || observer.deletes[0].Outcome != DeleteMissing {
		t.Fatalf("after-delete outcome = %+v", observer.deletes)
	}
	if limit := pod.Spec.Containers[0].Resources.Limits[corev1.ResourceCPU]; limit.String() != "1" {
		t.Fatalf("observer changed the pod spec: cpu limit %s", limit.String())
	}
}

func TestObserverSnapshotKeepsFractionalLifecycleBoundaries(t *testing.T) {
	started := time.Date(2026, 9, 18, 12, 0, 0, 123456789, time.UTC)
	ttl := 1500*time.Millisecond + 321*time.Nanosecond
	template := taskPod("template", "old-task", statusWaiting)
	pod := taskPodFromTemplate(*template, "test", "workspace-1", "task-1", started, ttl)
	pod.UID = types.UID("fractional-pod")
	snapshot := taskPodSnapshot(pod)
	assigned, err := time.Parse(time.RFC3339, snapshot.AssignedAt)
	if err != nil || !assigned.Equal(started) {
		t.Fatalf("assignment boundary = %q, want %s", snapshot.AssignedAt, started)
	}
	expiry, err := time.Parse(time.RFC3339, snapshot.LeaseUntil)
	if err != nil || !expiry.Equal(started.Add(ttl)) {
		t.Fatalf("lease boundary = %q, want %s", snapshot.LeaseUntil, started.Add(ttl))
	}
}
