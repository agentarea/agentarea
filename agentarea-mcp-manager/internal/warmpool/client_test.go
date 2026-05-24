package warmpool

import (
	"context"
	"testing"
	"time"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/fake"
)

func TestRetirePodForWorkflowMarksPodIdle(t *testing.T) {
	ctx := context.Background()
	clientset := fake.NewSimpleClientset(workflowPod("sandbox-1", "wf-1", statusAssigned))
	client := NewClient(clientset, "test")

	if err := client.RetirePodForWorkflow(ctx, "wf-1", 15*time.Minute); err != nil {
		t.Fatalf("RetirePodForWorkflow() error = %v", err)
	}

	pod, err := clientset.CoreV1().Pods("test").Get(ctx, "sandbox-1", metav1.GetOptions{})
	if err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if got := pod.Labels[labelStatus]; got != statusIdle {
		t.Fatalf("status = %q, want %q", got, statusIdle)
	}
	if pod.Annotations[annotationWorkflowCleanupAt] == "" {
		t.Fatal("cleanup annotation is empty")
	}
	if pod.Annotations[annotationWorkflowLeaseUntil] != "" {
		t.Fatal("lease annotation should be cleared for idle pods")
	}
}

func TestFindOrAssignPodForWorkflowReactivatesIdlePod(t *testing.T) {
	ctx := context.Background()
	pod := workflowPod("sandbox-1", "wf-1", statusIdle)
	pod.Annotations = map[string]string{
		annotationWorkflowCleanupAt: time.Now().Add(15 * time.Minute).UTC().Format(time.RFC3339),
	}
	clientset := fake.NewSimpleClientset(pod)
	client := NewClient(clientset, "test")

	assigned, err := client.FindOrAssignPodForWorkflow(ctx, "wf-1")
	if err != nil {
		t.Fatalf("FindOrAssignPodForWorkflow() error = %v", err)
	}
	if assigned.Name != "sandbox-1" {
		t.Fatalf("pod name = %q, want sandbox-1", assigned.Name)
	}
	if got := assigned.Labels[labelStatus]; got != statusAssigned {
		t.Fatalf("status = %q, want %q", got, statusAssigned)
	}
	if assigned.Annotations[annotationWorkflowCleanupAt] != "" {
		t.Fatal("cleanup annotation should be cleared after reactivation")
	}
	if assigned.Annotations[annotationWorkflowLeaseUntil] == "" {
		t.Fatal("lease annotation is empty after reactivation")
	}
}

func TestDeleteExpiredWorkflowPodsDeletesIdleAfterCleanupDeadline(t *testing.T) {
	ctx := context.Background()
	now := time.Now().UTC()
	expired := workflowPod("expired", "wf-expired", statusIdle)
	expired.Annotations = map[string]string{
		annotationWorkflowCleanupAt: now.Add(-time.Minute).Format(time.RFC3339),
	}
	fresh := workflowPod("fresh", "wf-fresh", statusIdle)
	fresh.Annotations = map[string]string{
		annotationWorkflowCleanupAt: now.Add(time.Minute).Format(time.RFC3339),
	}

	clientset := fake.NewSimpleClientset(expired, fresh)
	client := NewClient(clientset, "test")

	deleted, err := client.DeleteExpiredWorkflowPods(ctx, now)
	if err != nil {
		t.Fatalf("DeleteExpiredWorkflowPods() error = %v", err)
	}
	if deleted != 1 {
		t.Fatalf("deleted = %d, want 1", deleted)
	}
	if _, err := clientset.CoreV1().Pods("test").Get(ctx, "expired", metav1.GetOptions{}); err == nil {
		t.Fatal("expired pod still exists")
	}
	if _, err := clientset.CoreV1().Pods("test").Get(ctx, "fresh", metav1.GetOptions{}); err != nil {
		t.Fatalf("fresh pod missing: %v", err)
	}
}

func workflowPod(name, workflowID, status string) *corev1.Pod {
	return &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: "test",
			Labels: map[string]string{
				labelComponent:  "warm-pool",
				labelWorkflowID: workflowID,
				labelStatus:     status,
			},
			Annotations: map[string]string{},
		},
		Status: corev1.PodStatus{
			Phase: corev1.PodRunning,
			PodIP: "10.0.0.1",
		},
	}
}
