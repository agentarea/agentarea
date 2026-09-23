package warmpool

import (
	"context"
	"errors"
	"reflect"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/usage"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/kubernetes/fake"
	k8stesting "k8s.io/client-go/testing"
)

type podUsageRecorder struct{ events map[string]usage.Event }

func (r *podUsageRecorder) Record(_ context.Context, event usage.Event) error {
	if r.events == nil {
		r.events = make(map[string]usage.Event)
	}
	if old, ok := r.events[event.ID]; ok && !reflect.DeepEqual(old, event) {
		return errors.New("event collision")
	}
	r.events[event.ID] = event
	return nil
}

func TestPodUsageAllocationIsStableAcrossLeasesAndChangesWithUID(t *testing.T) {
	pod := taskPod("sandbox-1", "task-1", statusAssigned)
	pod.UID = types.UID("first")
	pod.Annotations[annotationTaskAssignedAt] = time.Now().UTC().Format(time.RFC3339)
	clientset := fake.NewSimpleClientset(pod)
	client := NewClient(clientset, "test", time.Hour)
	recorder := &podUsageRecorder{}
	client.SetUsageRecorder(recorder)
	ctx := context.Background()
	if err := client.TouchTaskPod(ctx, pod, time.Hour); err != nil {
		t.Fatal(err)
	}
	if err := client.TouchTaskPod(ctx, pod, time.Hour); err != nil {
		t.Fatal(err)
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
	allocations := make(map[string]bool)
	for _, event := range recorder.events {
		if event.Kind == "sandbox.allocated" {
			allocations[event.IncarnationID] = true
		}
	}
	if len(allocations) != 2 || !allocations["first"] || !allocations["replacement"] {
		t.Fatalf("allocation identities = %v", allocations)
	}
}

func TestPodUsageDeleteFailureNeverClaimsTermination(t *testing.T) {
	pod := taskPod("sandbox-1", "task-1", statusAssigned)
	pod.UID = types.UID("first")
	pod.Annotations[annotationTaskAssignedAt] = time.Now().UTC().Format(time.RFC3339)
	clientset := fake.NewSimpleClientset(pod)
	clientset.PrependReactor("delete", "pods", func(k8stesting.Action) (bool, runtime.Object, error) { return true, nil, errors.New("API unavailable") })
	client := NewClient(clientset, "test", time.Hour)
	recorder := &podUsageRecorder{}
	client.SetUsageRecorder(recorder)
	if err := client.RetirePodForTask(context.Background(), "workspace-1", "task-1", 0); err == nil {
		t.Fatal("expected delete failure")
	}
	failed := false
	for _, event := range recorder.events {
		if event.Kind == "sandbox.delete_accepted" || event.Kind == "sandbox.terminated" {
			t.Fatalf("unproven deletion: %s", event.Kind)
		}
		failed = failed || event.Kind == "sandbox.delete_failed"
	}
	if !failed {
		t.Fatal("missing failed-delete observation")
	}
}

func TestTaskPodUsagePreservesFractionalLifecycleBoundaries(t *testing.T) {
	started := time.Date(2026, 9, 18, 12, 0, 0, 123456789, time.UTC)
	ttl := 1500*time.Millisecond + 321*time.Nanosecond
	template := taskPod("template", "old-task", statusWaiting)
	pod := taskPodFromTemplate(*template, "test", "workspace-1", "task-1", started, ttl)
	pod.UID = types.UID("fractional-pod")
	client := NewClient(fake.NewSimpleClientset(pod), "test", ttl)
	recorder := &podUsageRecorder{}
	client.SetUsageRecorder(recorder)
	if err := client.recordPodLease(context.Background(), pod); err != nil {
		t.Fatal(err)
	}
	var allocation usage.Event
	for _, event := range recorder.events {
		if event.Kind == "sandbox.allocated" {
			allocation = event
		}
	}
	if !allocation.OccurredAt.Equal(started) {
		t.Fatalf("allocation start = %s, want %s", allocation.OccurredAt, started)
	}
	expiry, err := time.Parse(time.RFC3339, pod.Annotations[annotationTaskLeaseUntil])
	if err != nil {
		t.Fatal(err)
	}
	if !expiry.Equal(started.Add(ttl)) {
		t.Fatalf("lease boundary = %s, want %s", expiry, started.Add(ttl))
	}
}
