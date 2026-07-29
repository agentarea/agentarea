package warmpool

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/fake"
)

func TestRetirePodForTaskMarksPodIdle(t *testing.T) {
	ctx := context.Background()
	clientset := fake.NewSimpleClientset(taskPod("sandbox-1", "task-1", statusAssigned))
	client := NewClient(clientset, "test")

	if err := client.RetirePodForTask(ctx, "task-1", 15*time.Minute); err != nil {
		t.Fatalf("RetirePodForTask() error = %v", err)
	}

	pod, err := clientset.CoreV1().Pods("test").Get(ctx, "sandbox-1", metav1.GetOptions{})
	if err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if got := pod.Labels[labelStatus]; got != statusIdle {
		t.Fatalf("status = %q, want %q", got, statusIdle)
	}
	if pod.Annotations[annotationTaskCleanupAt] == "" {
		t.Fatal("cleanup annotation is empty")
	}
	if pod.Annotations[annotationTaskLeaseUntil] != "" {
		t.Fatal("lease annotation should be cleared for idle pods")
	}
}

func TestFindOrAssignPodForTaskReactivatesIdlePod(t *testing.T) {
	ctx := context.Background()
	pod := taskPod("sandbox-1", "task-1", statusIdle)
	pod.Annotations = map[string]string{
		annotationTaskCleanupAt: time.Now().Add(15 * time.Minute).UTC().Format(time.RFC3339),
	}
	clientset := fake.NewSimpleClientset(pod)
	client := NewClient(clientset, "test")

	assigned, err := client.FindOrAssignPodForTask(ctx, "task-1", runtimeinfo.PackageInstallAllowed)
	if err != nil {
		t.Fatalf("FindOrAssignPodForTask() error = %v", err)
	}
	if assigned.Name != "sandbox-1" {
		t.Fatalf("pod name = %q, want sandbox-1", assigned.Name)
	}
	if got := assigned.Labels[labelStatus]; got != statusAssigned {
		t.Fatalf("status = %q, want %q", got, statusAssigned)
	}
	if assigned.Annotations[annotationTaskCleanupAt] != "" {
		t.Fatal("cleanup annotation should be cleared after reactivation")
	}
	if assigned.Annotations[annotationTaskLeaseUntil] == "" {
		t.Fatal("lease annotation is empty after reactivation")
	}
}

func TestFindOrAssignPodForTaskExtendsAssignedLease(t *testing.T) {
	ctx := context.Background()
	pod := taskPod("sandbox-1", "task-1", statusAssigned)
	oldLease := time.Now().Add(time.Minute).UTC().Format(time.RFC3339)
	pod.Annotations[annotationTaskLeaseUntil] = oldLease
	clientset := fake.NewSimpleClientset(pod)
	client := NewClient(clientset, "test")

	if _, err := client.FindOrAssignPodForTask(ctx, "task-1", runtimeinfo.PackageInstallAllowed); err != nil {
		t.Fatalf("FindOrAssignPodForTask() error = %v", err)
	}
	updated, err := clientset.CoreV1().Pods("test").Get(ctx, "sandbox-1", metav1.GetOptions{})
	if err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if updated.Annotations[annotationTaskLeaseUntil] == oldLease {
		t.Fatal("assigned task lease was not extended")
	}
}

func TestFindAvailablePodFiltersExactPackageInstallProfile(t *testing.T) {
	ctx := context.Background()
	allowed := waitingPoolPod("allowed", runtimeinfo.PackageInstallAllowed)
	locked := waitingPoolPod("locked", runtimeinfo.PackageInstallLocked)
	client := NewClient(fake.NewSimpleClientset(allowed, locked), "test")

	pod, err := client.FindAvailablePod(ctx, runtimeinfo.PackageInstallLocked)
	if err != nil {
		t.Fatalf("FindAvailablePod() error = %v", err)
	}
	if pod.Name != "locked" {
		t.Fatalf("pod = %q, want locked", pod.Name)
	}
}

func TestFindAvailablePodRejectsMissingPackageInstallProfile(t *testing.T) {
	client := NewClient(fake.NewSimpleClientset(waitingPoolPod("allowed", runtimeinfo.PackageInstallAllowed)), "test")

	_, err := client.FindAvailablePod(context.Background(), "")
	if err == nil || !strings.Contains(err.Error(), "package_install") {
		t.Fatalf("FindAvailablePod() error = %v, want package_install validation", err)
	}
}

func TestFindRuntimeManifestPodUsesAssignedOnlyPoolWithoutMutation(t *testing.T) {
	ctx := context.Background()
	assigned := taskPod("assigned-runtime", "task-1", statusAssigned)
	assigned.Status.Conditions = []corev1.PodCondition{
		{Type: corev1.PodReady, Status: corev1.ConditionTrue},
	}
	clientset := fake.NewSimpleClientset(assigned)
	client := NewClient(clientset, "test")

	pod, err := client.FindRuntimeManifestPod(ctx, runtimeinfo.PackageInstallAllowed)
	if err != nil {
		t.Fatalf("FindRuntimeManifestPod() error = %v", err)
	}
	if pod.Name != "assigned-runtime" {
		t.Fatalf("pod = %q, want assigned-runtime", pod.Name)
	}

	stored, err := clientset.CoreV1().Pods("test").Get(ctx, assigned.Name, metav1.GetOptions{})
	if err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if got := stored.Labels[labelStatus]; got != statusAssigned {
		t.Fatalf("status = %q, want unchanged %q", got, statusAssigned)
	}
	if got := stored.Labels[labelTaskID]; got != "task-1" {
		t.Fatalf("task id = %q, want unchanged task-1", got)
	}
}

func TestFindRuntimeManifestPodSkipsUnreadyAndTerminalPods(t *testing.T) {
	unready := taskPod("unready", "task-1", statusAssigned)
	terminal := taskPod("terminal", "task-2", statusAssigned)
	terminal.Status.Phase = corev1.PodFailed
	terminal.Status.Conditions = []corev1.PodCondition{
		{Type: corev1.PodReady, Status: corev1.ConditionTrue},
	}
	client := NewClient(fake.NewSimpleClientset(unready, terminal), "test")

	_, err := client.FindRuntimeManifestPod(context.Background(), runtimeinfo.PackageInstallAllowed)
	if err == nil || !strings.Contains(err.Error(), "no ready runtime pods") {
		t.Fatalf("FindRuntimeManifestPod() error = %v, want no ready runtime pods", err)
	}
}

func TestFindOrAssignPodForTaskRejectsProfileChange(t *testing.T) {
	ctx := context.Background()
	assigned := taskPod("sandbox-1", "task-1", statusAssigned)
	assigned.Labels[labelPackageInstall] = runtimeinfo.PackageInstallAllowed
	locked := waitingPoolPod("locked", runtimeinfo.PackageInstallLocked)
	clientset := fake.NewSimpleClientset(assigned, locked)
	client := NewClient(clientset, "test")

	_, err := client.FindOrAssignPodForTask(ctx, "task-1", runtimeinfo.PackageInstallLocked)
	if err == nil || !strings.Contains(err.Error(), "profile") {
		t.Fatalf("FindOrAssignPodForTask() error = %v, want profile mismatch", err)
	}
	lockedAfter, getErr := clientset.CoreV1().Pods("test").Get(ctx, "locked", metav1.GetOptions{})
	if getErr != nil {
		t.Fatal(getErr)
	}
	if got := lockedAfter.Labels[labelTaskID]; got != "" {
		t.Fatalf("locked pod task assignment = %q, want unchanged", got)
	}
}

func TestFindOrAssignPodForTaskDoesNotUseMismatchedWaitingPod(t *testing.T) {
	ctx := context.Background()
	allowed := waitingPoolPod("allowed", runtimeinfo.PackageInstallAllowed)
	client := NewClient(fake.NewSimpleClientset(allowed), "test")

	_, err := client.FindOrAssignPodForTask(ctx, "task-1", runtimeinfo.PackageInstallLocked)
	if err == nil || !strings.Contains(err.Error(), "locked") {
		t.Fatalf("FindOrAssignPodForTask() error = %v, want unavailable locked pool", err)
	}
}

func TestDeleteExpiredTaskPodsDeletesIdleAfterCleanupDeadline(t *testing.T) {
	ctx := context.Background()
	now := time.Now().UTC()
	expired := taskPod("expired", "task-expired", statusIdle)
	expired.Annotations = map[string]string{
		annotationTaskCleanupAt: now.Add(-time.Minute).Format(time.RFC3339),
	}
	fresh := taskPod("fresh", "task-fresh", statusIdle)
	fresh.Annotations = map[string]string{
		annotationTaskCleanupAt: now.Add(time.Minute).Format(time.RFC3339),
	}

	clientset := fake.NewSimpleClientset(expired, fresh)
	client := NewClient(clientset, "test")

	deleted, err := client.DeleteExpiredTaskPods(ctx, now)
	if err != nil {
		t.Fatalf("DeleteExpiredTaskPods() error = %v", err)
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

func TestTaskPodFromTemplatePreservesIsolationIdentity(t *testing.T) {
	automount := true
	template := corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Labels: map[string]string{
				"app.kubernetes.io/name":     "agentarea",
				"app.kubernetes.io/instance": "test-release",
				labelComponent:               "warm-pool",
			},
		},
		Spec: corev1.PodSpec{
			ServiceAccountName:           "agentarea-mcp-runtime",
			AutomountServiceAccountToken: &automount,
			NodeName:                     "worker-1",
		},
	}

	pod := taskPodFromTemplate(template, "test", "task-123", time.Now().UTC(), time.Hour)

	if pod.Labels["app.kubernetes.io/name"] != "agentarea" || pod.Labels["app.kubernetes.io/instance"] != "test-release" {
		t.Fatalf("release selector labels were not preserved: %#v", pod.Labels)
	}
	if pod.Labels[labelComponent] != "workflow-sandbox" || pod.Labels[labelTaskID] != "task-123" {
		t.Fatalf("task isolation labels are incorrect: %#v", pod.Labels)
	}
	if pod.Spec.ServiceAccountName != "agentarea-mcp-runtime" {
		t.Fatalf("service account = %q", pod.Spec.ServiceAccountName)
	}
	if pod.Spec.AutomountServiceAccountToken == nil || *pod.Spec.AutomountServiceAccountToken {
		t.Fatal("task pod must not automount a service account token")
	}
	if pod.Spec.NodeName != "" {
		t.Fatalf("node name = %q, want scheduler assignment", pod.Spec.NodeName)
	}
}

func TestDefaultTaskLeaseTTLIgnoresWorkflowSetting(t *testing.T) {
	t.Setenv("SANDBOX_TASK_LEASE_TTL", "")
	t.Setenv("SANDBOX_WORKFLOW_LEASE_TTL", "1s")
	if got := defaultTaskLeaseTTL(); got != 2*time.Hour {
		t.Fatalf("defaultTaskLeaseTTL() = %s, want task default", got)
	}
}

func taskPod(name, taskID, status string) *corev1.Pod {
	return &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: "test",
			Labels: map[string]string{
				labelComponent:      "warm-pool",
				labelTaskID:         taskID,
				labelStatus:         status,
				labelPackageInstall: runtimeinfo.PackageInstallAllowed,
			},
			Annotations: map[string]string{},
		},
		Status: corev1.PodStatus{
			Phase: corev1.PodRunning,
			PodIP: "10.0.0.1",
		},
	}
}

func waitingPoolPod(name, packageInstall string) *corev1.Pod {
	pod := taskPod(name, "", statusWaiting)
	pod.Labels[labelPackageInstall] = packageInstall
	return pod
}
