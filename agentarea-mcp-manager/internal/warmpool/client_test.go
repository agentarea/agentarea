package warmpool

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/activationauth"
	"github.com/agentarea/mcp-manager/internal/execsupervisor"
	corev1 "k8s.io/api/core/v1"
	k8serrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	k8sruntime "k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/kubernetes/fake"
	k8stesting "k8s.io/client-go/testing"
)

func TestExecuteTransportTimeoutReservesSupervisorCompletionProof(t *testing.T) {
	base := 3 * time.Second
	if got := executeTransportTimeout(0, base); got != base {
		t.Fatalf("default transport timeout = %s, want %s", got, base)
	}
	want := 124*time.Second + execsupervisor.TransportGrace
	if got := executeTransportTimeout(124, base); got != want {
		t.Fatalf("explicit transport timeout = %s, want %s", got, want)
	}
	if execsupervisor.TransportGrace <= execsupervisor.CompletionGrace {
		t.Fatalf("transport grace %s must exceed supervisor completion grace %s", execsupervisor.TransportGrace, execsupervisor.CompletionGrace)
	}
}

func TestMutationTransportsSurfaceUnsafeExecutorIncarnation(t *testing.T) {
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("X-Agentarea-Executor-Unsafe", "true")
		http.Error(w, "discarded", http.StatusInsufficientStorage)
	}))
	defer server.Close()

	if _, err := PostExecute(context.Background(), server.URL, ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1",
		CommandBody: "true",
	}, time.Second); !errors.Is(err, ErrExecutorUnsafe) {
		t.Fatalf("PostExecute() error = %v, want ErrExecutorUnsafe", err)
	}
	if _, err := PutFile(context.Background(), server.URL, FilePutRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", Path: "result.txt", ContentBase64: "eA==",
	}, time.Second); !errors.Is(err, ErrExecutorUnsafe) {
		t.Fatalf("PutFile() error = %v, want ErrExecutorUnsafe", err)
	}
	digest := sha256.Sum256([]byte("x"))
	if _, err := PutFileStream(context.Background(), server.URL, FileTransferRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", Path: "result.txt", Size: 1,
		SHA256: hex.EncodeToString(digest[:]), Mode: 0o600,
	}, bytes.NewReader([]byte("x")), time.Second); !errors.Is(err, ErrExecutorUnsafe) {
		t.Fatalf("PutFileStream() error = %v, want ErrExecutorUnsafe", err)
	}
}

func TestDeleteExactPodCannotDeleteReplacementWithSameName(t *testing.T) {
	replacement := taskPod("sandbox-1", "task-1", statusAssigned)
	replacement.UID = types.UID("pod-b")
	clientset := fake.NewSimpleClientset(replacement)
	clientset.PrependReactor("delete", "pods", func(action k8stesting.Action) (bool, k8sruntime.Object, error) {
		deleteAction := action.(k8stesting.DeleteAction)
		options := deleteAction.GetDeleteOptions()
		if options.Preconditions == nil || options.Preconditions.UID == nil {
			t.Fatal("exact pod deletion omitted the Kubernetes UID precondition")
		}
		if got := *options.Preconditions.UID; got != types.UID("pod-a") {
			t.Fatalf("delete UID precondition = %q, want pod-a", got)
		}
		return true, nil, k8serrors.NewConflict(schema.GroupResource{Resource: "pods"}, replacement.Name, errors.New("UID precondition failed"))
	})
	client := NewClient(clientset, "test", time.Hour)
	captured := replacement.DeepCopy()
	captured.UID = types.UID("pod-a")

	if err := client.DeleteExactPod(context.Background(), captured); err == nil {
		t.Fatal("stale exact-pod cleanup unexpectedly deleted a replacement incarnation")
	}
	if _, err := clientset.CoreV1().Pods("test").Get(context.Background(), replacement.Name, metav1.GetOptions{}); err != nil {
		t.Fatalf("replacement pod was removed by stale cleanup: %v", err)
	}
}

func TestRetirePodForTaskMarksPodIdle(t *testing.T) {
	ctx := context.Background()
	clientset := fake.NewSimpleClientset(taskPod("sandbox-1", "task-1", statusAssigned))
	client := NewClient(clientset, "test", 2*time.Hour)

	if err := client.RetirePodForTask(ctx, "workspace-1", "task-1", 15*time.Minute); err != nil {
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

func TestRetirePodForTaskRefusesLiveOperation(t *testing.T) {
	ctx := context.Background()
	pod := taskPod("sandbox-1", "task-1", statusAssigned)
	clientset := fake.NewSimpleClientset(pod)
	client := NewClient(clientset, "test", 2*time.Hour)
	operation, err := client.BeginTaskOperation(ctx, pod, time.Minute)
	if err != nil {
		t.Fatal(err)
	}

	if err := client.RetirePodForTask(ctx, "workspace-1", "task-1", 15*time.Minute); !errors.Is(err, ErrTaskPodBusy) {
		t.Fatalf("RetirePodForTask() error = %v, want ErrTaskPodBusy", err)
	}
	if err := client.EndTaskOperation(ctx, operation); err != nil {
		t.Fatal(err)
	}
	if err := client.RetirePodForTask(ctx, "workspace-1", "task-1", 15*time.Minute); err != nil {
		t.Fatalf("RetirePodForTask() after operation error = %v", err)
	}
}

func TestFindOrAssignPodForTaskReactivatesIdlePod(t *testing.T) {
	ctx := context.Background()
	pod := taskPod("sandbox-1", "task-1", statusIdle)
	pod.Annotations = map[string]string{
		annotationTaskCleanupAt: time.Now().Add(15 * time.Minute).UTC().Format(time.RFC3339),
		annotationWorkspaceID:   "workspace-1",
		annotationTaskID:        "task-1",
	}
	clientset := fake.NewSimpleClientset(pod)
	client := NewClient(clientset, "test", 2*time.Hour)

	assigned, err := client.FindOrAssignPodForTask(ctx, "workspace-1", "task-1")
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
	client := NewClient(clientset, "test", 2*time.Hour)

	if _, err := client.FindOrAssignPodForTask(ctx, "workspace-1", "task-1"); err != nil {
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

func TestFindAvailablePodUsesConfiguredPool(t *testing.T) {
	ctx := context.Background()
	warm := waitingPoolPod("warm")
	client := NewClient(fake.NewSimpleClientset(warm), "test", 2*time.Hour)

	pod, err := client.FindAvailablePod(ctx)
	if err != nil {
		t.Fatalf("FindAvailablePod() error = %v", err)
	}
	if pod.Name != "warm" {
		t.Fatalf("pod = %q, want warm", pod.Name)
	}
}

func TestFindRuntimeManifestPodUsesAssignedOnlyPoolWithoutMutation(t *testing.T) {
	ctx := context.Background()
	assigned := taskPod("assigned-runtime", "task-1", statusAssigned)
	assigned.Status.Conditions = []corev1.PodCondition{
		{Type: corev1.PodReady, Status: corev1.ConditionTrue},
	}
	clientset := fake.NewSimpleClientset(assigned)
	client := NewClient(clientset, "test", 2*time.Hour)

	pod, err := client.FindRuntimeManifestPod(ctx)
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
	if got := stored.Annotations[annotationTaskID]; got != "task-1" {
		t.Fatalf("task id annotation = %q, want unchanged task-1", got)
	}
}

func TestFindRuntimeManifestPodSkipsUnreadyAndTerminalPods(t *testing.T) {
	unready := taskPod("unready", "task-1", statusAssigned)
	unready.Status.Conditions = nil
	terminal := taskPod("terminal", "task-2", statusAssigned)
	terminal.Status.Phase = corev1.PodFailed
	terminal.Status.Conditions = []corev1.PodCondition{
		{Type: corev1.PodReady, Status: corev1.ConditionTrue},
	}
	client := NewClient(fake.NewSimpleClientset(unready, terminal), "test", 2*time.Hour)

	_, err := client.FindRuntimeManifestPod(context.Background())
	if err == nil || !strings.Contains(err.Error(), "no ready runtime pods") {
		t.Fatalf("FindRuntimeManifestPod() error = %v, want no ready runtime pods", err)
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
	client := NewClient(clientset, "test", 2*time.Hour)

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

func TestDeleteExpiredTaskPodsSkipsPodWithLiveOperation(t *testing.T) {
	ctx := context.Background()
	now := time.Now().UTC()
	pod := taskPod("busy", "task-1", statusIdle)
	pod.Annotations[annotationTaskCleanupAt] = now.Add(-time.Minute).Format(time.RFC3339)
	clientset := fake.NewSimpleClientset(pod)
	client := NewClient(clientset, "test", 2*time.Hour)
	if _, err := client.BeginTaskOperation(ctx, pod, time.Minute); err != nil {
		t.Fatal(err)
	}

	deleted, err := client.DeleteExpiredTaskPods(ctx, now)
	if err != nil {
		t.Fatal(err)
	}
	if deleted != 0 {
		t.Fatalf("deleted = %d, want 0", deleted)
	}
	if _, err := clientset.CoreV1().Pods("test").Get(ctx, pod.Name, metav1.GetOptions{}); err != nil {
		t.Fatalf("busy pod was deleted: %v", err)
	}
}

func TestListTaskPodsForWorkspaceValidatesAndScopesLiveInventory(t *testing.T) {
	matching := taskPod("sandbox-1", "task-1", statusAssigned)
	other := taskPod("sandbox-2", "task-2", statusAssigned)
	other.Annotations[annotationWorkspaceID] = "workspace-2"
	other.Labels[labelTaskBinding] = taskBinding("workspace-2", "task-2")
	client := NewClient(fake.NewSimpleClientset(matching, other), "test", time.Hour)

	items, err := client.ListTaskPodsForWorkspace(context.Background(), "workspace-1")
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].TaskID != "task-1" || items[0].Isolation != "gvisor" {
		t.Fatalf("ListTaskPodsForWorkspace() = %+v", items)
	}
}

func TestWaitForPodRunningRequiresReadyCondition(t *testing.T) {
	pod := taskPod("unready", "task-1", statusAssigned)
	pod.Status.Conditions = nil
	client := NewClient(fake.NewSimpleClientset(pod), "test", time.Hour)
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()

	if _, err := client.waitForPodRunning(ctx, pod.Name, time.Second); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("waitForPodRunning() error = %v, want context deadline for unready pod", err)
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

	pod := taskPodFromTemplate(template, "test", "workspace-1", "task-123", time.Now().UTC(), time.Hour)

	if pod.Labels["app.kubernetes.io/name"] != "agentarea" || pod.Labels["app.kubernetes.io/instance"] != "test-release" {
		t.Fatalf("release selector labels were not preserved: %#v", pod.Labels)
	}
	if pod.Labels[labelComponent] != "workflow-sandbox" || pod.Annotations[annotationTaskID] != "task-123" {
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

func TestEnsurePodHydratedSerializesConcurrentManagerReplicas(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	clientset := fake.NewSimpleClientset(taskPod("sandbox-1", "task-1", statusAssigned))
	client := NewClient(clientset, "test", time.Hour)
	stubExecutorIncarnation(client, "test-incarnation")
	var calls atomic.Int32
	entered := make(chan struct{})
	release := make(chan struct{})
	errorsByCaller := make(chan error, 2)
	hydrate := func(context.Context) error {
		if calls.Add(1) == 1 {
			close(entered)
		}
		<-release
		return nil
	}
	go func() {
		errorsByCaller <- client.EnsurePodHydrated(ctx, "workspace-1", "task-1", strings.Repeat("a", 64), hydrate)
	}()
	<-entered
	go func() {
		errorsByCaller <- client.EnsurePodHydrated(ctx, "workspace-1", "task-1", strings.Repeat("a", 64), hydrate)
	}()
	time.Sleep(100 * time.Millisecond)
	if calls.Load() != 1 {
		t.Fatalf("hydrate calls while first claim is active = %d, want 1", calls.Load())
	}
	close(release)
	for range 2 {
		if err := <-errorsByCaller; err != nil {
			t.Fatal(err)
		}
	}
	if calls.Load() != 1 {
		t.Fatalf("hydrate calls = %d, want 1", calls.Load())
	}
	pod, err := clientset.CoreV1().Pods("test").Get(ctx, "sandbox-1", metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if pod.Annotations[annotationHydrationRev] != strings.Repeat("a", 64) || pod.Annotations[annotationHydrationClaim] != "" {
		t.Fatalf("hydration annotations = %#v", pod.Annotations)
	}
}

func TestEnsurePodHydratedRenewsTaskLeaseWhileMaterializingInputs(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	clientset := fake.NewSimpleClientset(taskPod("sandbox-1", "task-1", statusAssigned))
	client := NewClient(clientset, "test", 3*time.Second)
	stubExecutorIncarnation(client, "test-incarnation")
	entered := make(chan struct{})
	release := make(chan struct{})
	done := make(chan error, 1)

	go func() {
		done <- client.EnsurePodHydrated(ctx, "workspace-1", "task-1", strings.Repeat("b", 64), func(context.Context) error {
			close(entered)
			<-release
			return nil
		})
	}()
	<-entered
	initial, err := clientset.CoreV1().Pods("test").Get(ctx, "sandbox-1", metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	initialLease := initial.Annotations[annotationTaskLeaseUntil]
	time.Sleep(1200 * time.Millisecond)
	close(release)
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	updated, err := clientset.CoreV1().Pods("test").Get(ctx, "sandbox-1", metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if updated.Annotations[annotationTaskLeaseUntil] <= initialLease {
		t.Fatalf("task lease was not renewed during hydration: initial=%q updated=%q", initialLease, updated.Annotations[annotationTaskLeaseUntil])
	}
}

func TestVerifyOrBindExecutorIncarnationDeletesSameUIDRestart(t *testing.T) {
	pod := taskPod("sandbox-1", "task-1", statusAssigned)
	pod.UID = "pod-uid-1"
	pod.Annotations[annotationHydrationIncarnation] = "old-incarnation"
	clientset := fake.NewSimpleClientset(pod)
	client := NewClient(clientset, "test", time.Hour)
	stubExecutorIncarnation(client, "new-incarnation")

	_, _, err := client.VerifyOrBindExecutorIncarnation(context.Background(), pod)
	if !errors.Is(err, ErrExecutorIncarnationChanged) {
		t.Fatalf("VerifyOrBindExecutorIncarnation() error = %v, want ErrExecutorIncarnationChanged", err)
	}
	if _, getErr := clientset.CoreV1().Pods("test").Get(context.Background(), pod.Name, metav1.GetOptions{}); !k8serrors.IsNotFound(getErr) {
		t.Fatalf("same-UID restarted pod still exists: %v", getErr)
	}
}

func TestEnsurePodHydratedRejectsRestartBeforeCommit(t *testing.T) {
	pod := taskPod("sandbox-1", "task-1", statusAssigned)
	pod.UID = "pod-uid-1"
	clientset := fake.NewSimpleClientset(pod)
	client := NewClient(clientset, "test", time.Hour)
	var observations atomic.Int32
	client.observeExecutorIncarnation = func(context.Context, *corev1.Pod) (string, error) {
		if observations.Add(1) == 1 {
			return "old-incarnation", nil
		}
		return "new-incarnation", nil
	}

	err := client.EnsurePodHydrated(
		context.Background(), "workspace-1", "task-1",
		strings.Repeat("f", 64), func(context.Context) error { return nil },
	)
	if !errors.Is(err, ErrExecutorIncarnationChanged) {
		t.Fatalf("EnsurePodHydrated() error = %v, want ErrExecutorIncarnationChanged", err)
	}
	if _, getErr := clientset.CoreV1().Pods("test").Get(context.Background(), pod.Name, metav1.GetOptions{}); !k8serrors.IsNotFound(getErr) {
		t.Fatalf("pod restarted during hydration still exists: %v", getErr)
	}
}

func TestFindPodForTaskRejectsTamperedWorkspaceAnnotation(t *testing.T) {
	pod := taskPod("sandbox-1", "task-1", statusAssigned)
	pod.Annotations[annotationWorkspaceID] = "workspace-other"
	client := NewClient(fake.NewSimpleClientset(pod), "test", time.Hour)
	if _, err := client.FindPodForTask(context.Background(), "workspace-1", "task-1"); err == nil || !strings.Contains(err.Error(), "identity") {
		t.Fatalf("FindPodForTask() error = %v, want identity rejection", err)
	}
}

func taskPod(name, taskID, status string) *corev1.Pod {
	runtimeClass := "gvisor"
	return &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: "test",
			UID:       types.UID("uid-" + name),
			Labels: map[string]string{
				labelComponent:   "warm-pool",
				labelTaskBinding: taskBinding("workspace-1", taskID),
				labelStatus:      status,
			},
			Annotations: map[string]string{
				annotationWorkspaceID:          "workspace-1",
				annotationTaskID:               taskID,
				annotationHydrationIncarnation: "test-incarnation",
			},
		},
		Spec: corev1.PodSpec{RuntimeClassName: &runtimeClass},
		Status: corev1.PodStatus{
			Phase: corev1.PodRunning,
			PodIP: "10.0.0.1",
			Conditions: []corev1.PodCondition{{
				Type: corev1.PodReady, Status: corev1.ConditionTrue,
			}},
		},
	}
}

func stubExecutorIncarnation(client *Client, incarnation string) {
	client.observeExecutorIncarnation = func(context.Context, *corev1.Pod) (string, error) {
		return incarnation, nil
	}
}

func waitingPoolPod(name string) *corev1.Pod {
	pod := taskPod(name, "", statusWaiting)
	return pod
}
