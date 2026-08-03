package backends

import (
	"context"
	"fmt"
	"sync"

	"github.com/agentarea/mcp-manager/internal/sandboxruntime"
	"github.com/agentarea/mcp-manager/internal/warmpool"
	corev1 "k8s.io/api/core/v1"
)

type kubernetesOperationScopeKey struct{}

// kubernetesOperationScope carries the exact hydrated pod binding across the
// WorkspaceRuntime hydration -> execution composite. Its TaskOperation lives in
// a pod annotation, so manager, runner, reaper, and another replica all observe
// the same retirement fence.
type kubernetesOperationScope struct {
	mu                  sync.Mutex
	client              *warmpool.Client
	revision            string
	executorIncarnation string
	heartbeat           *podLeaseHeartbeat
	leaseCtx            context.Context
}

func operationScope(ctx context.Context) (*kubernetesOperationScope, bool) {
	scope, ok := ctx.Value(kubernetesOperationScopeKey{}).(*kubernetesOperationScope)
	return scope, ok && scope != nil
}

func (s *kubernetesOperationScope) bind(
	ctx context.Context,
	backend *KubernetesBackend,
	client *warmpool.Client,
	pod *corev1.Pod,
	revision string,
) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.heartbeat != nil {
		current, err := s.client.TaskPodForOperation(ctx, s.heartbeat.operation, s.revision)
		if err != nil || current.UID != pod.UID || s.revision != revision || s.executorIncarnation != s.heartbeat.operation.ExecutorIncarnation {
			return fmt.Errorf("%w: Kubernetes workspace binding changed", sandboxruntime.ErrWorkspaceRehydration)
		}
		return nil
	}
	leaseCtx, heartbeat, err := backend.startPodLease(ctx, client, pod)
	if err != nil {
		return fmt.Errorf("%w: bind hydrated Kubernetes workspace: %v", sandboxruntime.ErrWorkspaceRehydration, err)
	}
	s.client = client
	s.revision = revision
	s.executorIncarnation = heartbeat.operation.ExecutorIncarnation
	s.heartbeat = heartbeat
	s.leaseCtx = leaseCtx
	return nil
}

func (s *kubernetesOperationScope) incarnation() (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.executorIncarnation == "" {
		return "", fmt.Errorf("%w: Kubernetes executor incarnation is not bound", sandboxruntime.ErrWorkspaceRehydration)
	}
	return s.executorIncarnation, nil
}

func (s *kubernetesOperationScope) pod(ctx context.Context) (*corev1.Pod, context.Context, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.heartbeat == nil || s.client == nil || s.leaseCtx == nil {
		return nil, nil, fmt.Errorf("%w: Kubernetes workspace was not bound after hydration", sandboxruntime.ErrWorkspaceRehydration)
	}
	if err := ctx.Err(); err != nil {
		return nil, nil, err
	}
	pod, err := s.client.TaskPodForOperation(s.leaseCtx, s.heartbeat.operation, s.revision)
	if err != nil {
		return nil, nil, fmt.Errorf("%w: verify hydrated Kubernetes workspace: %v", sandboxruntime.ErrWorkspaceRehydration, err)
	}
	return pod, s.leaseCtx, nil
}

func (s *kubernetesOperationScope) bound() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.heartbeat != nil
}

func (s *kubernetesOperationScope) stop() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.heartbeat == nil {
		return nil
	}
	err := s.heartbeat.stop()
	s.heartbeat = nil
	s.leaseCtx = nil
	s.executorIncarnation = ""
	return err
}
