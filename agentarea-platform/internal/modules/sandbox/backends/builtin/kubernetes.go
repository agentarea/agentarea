package builtin

import (
	"fmt"
	"log/slog"
	"time"

	"k8s.io/client-go/kubernetes"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/sandboxruntime"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/warmpool"
)

// Kubernetes is the sandbox on the warm pool: a task holds a pod of the pool
// in the namespace, leased for taskLeaseTTL and fenced against retirement.
type Kubernetes struct {
	clientset    kubernetes.Interface
	executor     warmpool.Executor
	namespace    string
	logger       *slog.Logger
	taskLeaseTTL time.Duration
	// taskOperations fences composite task work against in-process retirement.
	taskOperations *sandboxruntime.TaskOperationGate
	taskObserver   warmpool.LifecycleObserver
}

// NewKubernetes is the warm-pool sandbox in namespace.
func NewKubernetes(clientset kubernetes.Interface, namespace string, taskLeaseTTL time.Duration, executor warmpool.Executor, logger *slog.Logger) (*Kubernetes, error) {
	if taskLeaseTTL <= 0 {
		return nil, fmt.Errorf("sandbox task lease TTL must be positive")
	}
	if clientset == nil || executor.Transport == nil {
		return nil, fmt.Errorf("the warm-pool sandbox needs a Kubernetes client and an executor transport")
	}
	return &Kubernetes{
		clientset: clientset, executor: executor, namespace: namespace, logger: logger, taskLeaseTTL: taskLeaseTTL,
		taskOperations: sandboxruntime.NewTaskOperationGate("kubernetes"),
	}, nil
}

var (
	_ sandboxruntime.ManagedRuntime = (*Docker)(nil)
	_ sandboxruntime.ManagedRuntime = (*Kubernetes)(nil)
)
