package backends

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime"
	"github.com/agentarea/mcp-manager/internal/warmpool"
	"github.com/agentarea/mcp-manager/internal/workspace"
	corev1 "k8s.io/api/core/v1"
)

func (k *KubernetesBackend) RuntimeManifest(ctx context.Context) (*runtimeinfo.Manifest, error) {
	client := k.GetWarmPoolClient()
	if client == nil {
		return nil, fmt.Errorf("sandbox warm pool client is not available")
	}
	pod, err := client.FindRuntimeManifestPod(ctx)
	if err != nil {
		return nil, err
	}
	return client.RuntimeManifestInPod(ctx, pod)
}

// GetWarmPoolClient returns a warm pool client for the current namespace.
func (k *KubernetesBackend) GetWarmPoolClient() *warmpool.Client {
	return warmpool.NewClient(k.clientset, k.k8sConfig.Namespace, k.taskLeaseTTL)
}

// ExecuteSandbox runs a sandbox script on the warm-pool data plane. TaskID
// selects a sticky session pod so state persists across calls; execution runs
// in place on that pod. Implements sandboxrunner.SandboxExecutor.
func (k *KubernetesBackend) ExecuteSandbox(ctx context.Context, req warmpool.ExecuteRequest) (*warmpool.ExecuteResponse, error) {
	if req.TaskID == "" {
		return nil, fmt.Errorf("task_id is required for sandbox execution")
	}
	wp := k.GetWarmPoolClient()
	if wp == nil {
		return nil, fmt.Errorf("warm pool client unavailable")
	}
	scope, ok := operationScope(ctx)
	if !ok {
		return nil, fmt.Errorf("%w: Kubernetes execution requires a hydrated operation scope", sandboxruntime.ErrWorkspaceRehydration)
	}
	pod, operationCtx, err := scope.pod(ctx)
	if err != nil {
		return nil, err
	}
	incarnation, err := scope.incarnation()
	if err != nil {
		return nil, err
	}
	req.ExecutorIncarnation = incarnation
	result, executeErr := wp.ExecuteInPod(operationCtx, pod, req)
	return result, k.invalidateUnsafePod(ctx, wp, pod, executeErr)
}

func (k *KubernetesBackend) invalidateUnsafePod(
	ctx context.Context,
	client *warmpool.Client,
	pod *corev1.Pod,
	operationErr error,
) error {
	if operationErr == nil || errors.Is(operationErr, warmpool.ErrFileNotFound) || errors.Is(operationErr, warmpool.ErrTaskWorkspaceGone) {
		return operationErr
	}
	cleanupCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 30*time.Second)
	deleteErr := client.DeleteExactPod(cleanupCtx, pod)
	cancel()
	reason := "sandbox data-plane operation failed with an ambiguous workspace state"
	if errors.Is(operationErr, warmpool.ErrExecutorUnsafe) {
		reason = "sandbox executor discarded its workspace"
	} else if errors.Is(operationErr, warmpool.ErrExecutorIncarnationChanged) {
		reason = "sandbox executor incarnation changed"
	}
	return errors.Join(
		fmt.Errorf("%w: %s", sandboxruntime.ErrWorkspaceRehydration, reason),
		operationErr,
		deleteErr,
	)
}

// BeginOperation creates a demand scope that is first fenced locally and, once
// hydration selects a pod, bound to that exact pod UID by a distributed
// TaskOperation annotation. Manager, runner, and reaper replicas therefore
// share the same retirement boundary across hydration and execution.
func (k *KubernetesBackend) BeginOperation(ctx context.Context, workspaceID, taskID string) (context.Context, func(), error) {
	if err := workspace.ValidateIdentifier("workspace_id", workspaceID); err != nil {
		return nil, nil, err
	}
	if err := workspace.ValidateIdentifier("task_id", taskID); err != nil {
		return nil, nil, err
	}
	operationCtx, releaseLocal, err := k.taskOperations.BeginOperation(ctx, workspaceID, taskID)
	if err != nil {
		return nil, nil, err
	}
	scope := &kubernetesOperationScope{}
	operationCtx = context.WithValue(operationCtx, kubernetesOperationScopeKey{}, scope)
	var once sync.Once
	return operationCtx, func() {
		once.Do(func() {
			if err := scope.stop(); err != nil {
				k.logger.Error("failed to release Kubernetes distributed task fence", "error", err)
			}
			releaseLocal()
		})
	}, nil
}

func (k *KubernetesBackend) RetireSandboxTask(ctx context.Context, workspaceID, taskID string, idleTTL time.Duration) error {
	if err := workspace.ValidateIdentifier("workspace_id", workspaceID); err != nil {
		return err
	}
	if err := workspace.ValidateIdentifier("task_id", taskID); err != nil {
		return err
	}
	ctx, release, err := k.taskOperations.BeginRetirement(ctx, workspaceID, taskID)
	if err != nil {
		return err
	}
	defer release()
	client := k.GetWarmPoolClient()
	if client == nil {
		return fmt.Errorf("sandbox warm pool client is not available")
	}
	return client.RetirePodForTask(ctx, workspaceID, taskID, idleTTL)
}

func (k *KubernetesBackend) ListSandboxes(ctx context.Context, workspaceID string) ([]sandboxruntime.SandboxStatus, error) {
	client := k.GetWarmPoolClient()
	if client == nil {
		return nil, fmt.Errorf("sandbox warm pool client is not available")
	}
	pods, err := client.ListTaskPodsForWorkspace(ctx, workspaceID)
	if err != nil {
		return nil, err
	}
	result := make([]sandboxruntime.SandboxStatus, 0, len(pods))
	for _, pod := range pods {
		result = append(result, sandboxruntime.SandboxStatus{
			ID: pod.ID, Provider: "kubernetes", WorkspaceID: pod.WorkspaceID,
			TaskID: pod.TaskID, State: pod.State,
			CreatedAt: pod.CreatedAt, ExpiresAt: pod.ExpiresAt,
			Resources: pod.Resources, Isolation: pod.Isolation,
		})
	}
	return result, nil
}

func (k *KubernetesBackend) EnsureWorkspaceHydrated(
	ctx context.Context,
	workspaceID, taskID, revision string,
	hydrate func(context.Context) error,
) error {
	client := k.GetWarmPoolClient()
	if client == nil {
		return fmt.Errorf("sandbox warm pool client is not available")
	}
	scope, ok := operationScope(ctx)
	if !ok {
		return fmt.Errorf("%w: Kubernetes hydration requires an operation scope", sandboxruntime.ErrWorkspaceRehydration)
	}
	pod, err := client.EnsurePodHydratedBinding(ctx, workspaceID, taskID, revision, hydrate)
	if err != nil {
		if errors.Is(err, warmpool.ErrExecutorIncarnationChanged) {
			return errors.Join(fmt.Errorf("%w: sandbox executor restarted during hydration", sandboxruntime.ErrWorkspaceRehydration), err)
		}
		return err
	}
	return scope.bind(ctx, k, client, pod, revision)
}
