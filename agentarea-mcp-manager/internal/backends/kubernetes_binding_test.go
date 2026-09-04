package backends

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"log/slog"
	"net"
	"net/http"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime"
	"github.com/agentarea/mcp-manager/internal/sandboxworkspace"
	"github.com/agentarea/mcp-manager/internal/warmpool"
	"github.com/agentarea/mcp-manager/internal/workspace"
	corev1 "k8s.io/api/core/v1"
	k8serrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	k8sruntime "k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/kubernetes/fake"
	k8stesting "k8s.io/client-go/testing"
)

func TestKubernetesBackendInvalidatesExactUnsafePodAndRequiresRehydration(t *testing.T) {
	pod := taskPodForUnsafeInvalidation("unsafe-pod", types.UID("pod-a"))
	clientset := fake.NewSimpleClientset(pod)
	backend := &KubernetesBackend{
		clientset: clientset,
		k8sConfig: &config.KubernetesConfig{Namespace: pod.Namespace},
	}

	err := backend.invalidateUnsafePod(
		context.Background(), backend.GetWarmPoolClient(), pod, warmpool.ErrExecutorUnsafe,
	)
	if !errors.Is(err, sandboxruntime.ErrWorkspaceRehydration) || !errors.Is(err, warmpool.ErrExecutorUnsafe) {
		t.Fatalf("invalidateUnsafePod() error = %v, want unsafe cause and rehydration requirement", err)
	}
	if _, getErr := clientset.CoreV1().Pods(pod.Namespace).Get(context.Background(), pod.Name, metav1.GetOptions{}); !k8serrors.IsNotFound(getErr) {
		t.Fatalf("unsafe pod still exists: %v", getErr)
	}
}

func taskPodForUnsafeInvalidation(name string, uid types.UID) *corev1.Pod {
	return &corev1.Pod{ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: "sandbox-test", UID: uid}}
}

type staticWorkspaceEnsurer struct {
	mount *sandboxworkspace.Mount
}

func (e staticWorkspaceEnsurer) Ensure(context.Context, string, string) (*sandboxworkspace.Mount, error) {
	return e.mount, nil
}

func TestKubernetesBackendRejectsReplacementPodAfterHydration(t *testing.T) {
	startExecutorHealthFixture(t)
	const (
		namespace   = "sandbox-test"
		workspaceID = "workspace-1"
		taskID      = "task-1"
		podName     = "task-binding-test"
	)
	bindingDigest := sha256.Sum256([]byte(workspaceID + "\x00" + taskID))
	binding := hex.EncodeToString(bindingDigest[:])[:52]
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name: podName, Namespace: namespace, UID: types.UID("pod-a"),
			Labels: map[string]string{
				"mcp.agentarea.io/task-binding": binding,
				"mcp.agentarea.io/status":       "assigned",
			},
			Annotations: map[string]string{
				"mcp.agentarea.io/workspace-id":     workspaceID,
				"mcp.agentarea.io/task-id":          taskID,
				"mcp.agentarea.io/task-lease-until": time.Now().Add(time.Hour).UTC().Format(time.RFC3339),
			},
		},
		Status: corev1.PodStatus{
			Phase: corev1.PodRunning, PodIP: "127.0.0.1",
			Conditions: []corev1.PodCondition{{
				Type: corev1.PodReady, Status: corev1.ConditionTrue,
			}},
		},
	}
	clientset := fake.NewSimpleClientset(pod)
	backend := &KubernetesBackend{
		clientset:      clientset,
		k8sConfig:      &config.KubernetesConfig{Namespace: namespace},
		logger:         slog.New(slog.NewTextHandler(io.Discard, nil)),
		taskLeaseTTL:   time.Hour,
		taskOperations: sandboxruntime.NewTaskOperationGate("kubernetes-test"),
	}
	ctx, release, err := backend.BeginOperation(context.Background(), workspaceID, taskID)
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	revision := "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	if err := backend.EnsureWorkspaceHydrated(
		ctx, workspaceID, taskID, revision,
		func(context.Context) error { return nil },
	); err != nil {
		t.Fatalf("EnsureWorkspaceHydrated() error = %v", err)
	}

	current, err := clientset.CoreV1().Pods(namespace).Get(ctx, podName, metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if err := clientset.CoreV1().Pods(namespace).Delete(ctx, podName, metav1.DeleteOptions{}); err != nil {
		t.Fatal(err)
	}
	replacement := current.DeepCopy()
	replacement.ResourceVersion = ""
	replacement.UID = types.UID("pod-b")
	if _, err := clientset.CoreV1().Pods(namespace).Create(ctx, replacement, metav1.CreateOptions{}); err != nil {
		t.Fatal(err)
	}

	_, err = backend.ExecuteSandbox(ctx, warmpool.ExecuteRequest{
		WorkspaceID: workspaceID, TaskID: taskID,
		CommandBody: "true",
	})
	if !errors.Is(err, sandboxruntime.ErrWorkspaceRehydration) {
		t.Fatalf("ExecuteSandbox() error = %v, want ErrWorkspaceRehydration", err)
	}
}

func TestWorkspaceRuntimeReadRejectsKubernetesPodReplacementAfterHydration(t *testing.T) {
	startExecutorHealthFixture(t)
	const (
		namespace   = "sandbox-test"
		workspaceID = "workspace-1"
		taskID      = "task-1"
		podName     = "task-binding-test"
	)
	bindingDigest := sha256.Sum256([]byte(workspaceID + "\x00" + taskID))
	binding := hex.EncodeToString(bindingDigest[:])[:52]
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name: podName, Namespace: namespace, UID: types.UID("pod-a"),
			Labels: map[string]string{
				"mcp.agentarea.io/task-binding": binding,
				"mcp.agentarea.io/status":       "assigned",
			},
			Annotations: map[string]string{
				"mcp.agentarea.io/workspace-id":     workspaceID,
				"mcp.agentarea.io/task-id":          taskID,
				"mcp.agentarea.io/task-lease-until": time.Now().Add(time.Hour).UTC().Format(time.RFC3339),
			},
		},
		Status: corev1.PodStatus{
			Phase: corev1.PodRunning, PodIP: "127.0.0.1",
			Conditions: []corev1.PodCondition{{Type: corev1.PodReady, Status: corev1.ConditionTrue}},
		},
	}
	clientset := fake.NewSimpleClientset(pod)
	clientset.PrependReactor("get", "pods", func(action k8stesting.Action) (bool, k8sruntime.Object, error) {
		get := action.(k8stesting.GetAction)
		object, err := clientset.Tracker().Get(corev1.SchemeGroupVersion.WithResource("pods"), namespace, get.GetName())
		if err != nil {
			return true, nil, err
		}
		current := object.(*corev1.Pod).DeepCopy()
		if current.Annotations["mcp.agentarea.io/task-operations"] == "" {
			return false, nil, nil
		}
		current.UID = types.UID("pod-b")
		return true, current, nil
	})
	backend := &KubernetesBackend{
		clientset:      clientset,
		k8sConfig:      &config.KubernetesConfig{Namespace: namespace},
		logger:         slog.New(slog.NewTextHandler(io.Discard, nil)),
		taskLeaseTTL:   time.Hour,
		taskOperations: sandboxruntime.NewTaskOperationGate("kubernetes-test"),
	}
	revision := "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	runtime, err := sandboxruntime.NewWorkspaceRuntime(backend, staticWorkspaceEnsurer{mount: &sandboxworkspace.Mount{
		WorkspaceID: workspaceID, TaskID: taskID, Root: sandboxruntime.WorkspaceRoot,
		RevisionSHA256: revision,
		Hydration:      workspace.Hydration{RevisionSHA256: revision},
	}})
	if err != nil {
		t.Fatal(err)
	}
	_, err = runtime.GetWorkspaceFile(context.Background(), sandboxruntime.WorkspaceFileRead{
		WorkspaceFileDemand: sandboxruntime.WorkspaceFileDemand{
			WorkspaceID: workspaceID, TaskID: taskID,
			Ensure: true,
		},
		Path: "inputs/example.txt",
	})
	if !errors.Is(err, sandboxruntime.ErrWorkspaceRehydration) {
		t.Fatalf("GetWorkspaceFile() error = %v, want ErrWorkspaceRehydration", err)
	}
}

func startExecutorHealthFixture(t *testing.T) {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:8080")
	if err != nil {
		t.Fatalf("listen for executor health fixture: %v", err)
	}
	server := &http.Server{Handler: http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/health" {
			http.NotFound(response, request)
			return
		}
		response.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(response, `{"status":"ok","incarnation":"11111111-1111-4111-8111-111111111111"}`)
	})}
	go func() { _ = server.Serve(listener) }()
	t.Cleanup(func() { _ = server.Close() })
}
