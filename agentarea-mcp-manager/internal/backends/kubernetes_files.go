package backends

import (
	"context"
	"fmt"
	"time"

	corev1 "k8s.io/api/core/v1"

	"github.com/agentarea/mcp-manager/internal/warmpool"
)

// The sandbox file API on the Kubernetes backend.
//
// Until now only the docker backend implemented it, and the production
// warm-pool path answered 503. That made the file tool a development-only
// feature: on Kubernetes the agent could execute commands but not put a file
// where those commands would see it, so files fell back to the S3 task
// workspace that bash cannot read — the split-brain between the two surfaces.
//
// Routing is by the task's already-assigned pod, never a newly created one.
// FindPodForTask exists for exactly this reason (its own contract: "writeback
// must target the same pod that executed the command; creating a replacement
// would lose its workspace changes"), and it refreshes the lease, so touching
// files keeps the sandbox alive the same way executing does.

const sandboxFileTimeout = 30 * time.Second

// taskPodBaseURL resolves the activation service on the pod already serving the
// task. It deliberately does not create one: FilePutRequest carries no runtime
// profile, so assigning a pod here would mean inventing a package-install
// value — and inventing it wrongly would hand a locked task an unlocked
// sandbox. A task with no pod yet is reported as such.
func (k *KubernetesBackend) taskPodBaseURL(ctx context.Context, taskID string) (string, error) {
	if taskID == "" {
		return "", fmt.Errorf("task_id is required for sandbox file access")
	}
	wp := k.GetWarmPoolClient()
	if wp == nil {
		return "", fmt.Errorf("warm pool client unavailable")
	}
	pod, err := wp.FindPodForTask(ctx, taskID)
	if err != nil {
		return "", err
	}
	return podActivationURL(pod)
}

func podActivationURL(pod *corev1.Pod) (string, error) {
	if pod.Status.PodIP == "" {
		return "", fmt.Errorf("sandbox pod %s has no IP address yet", pod.Name)
	}
	return fmt.Sprintf("http://%s:8080", pod.Status.PodIP), nil
}

// SandboxFilePut writes a file into the task's live sandbox filesystem.
func (k *KubernetesBackend) SandboxFilePut(ctx context.Context, req warmpool.FilePutRequest) (*warmpool.FilePutResponse, error) {
	base, err := k.taskPodBaseURL(ctx, req.TaskID)
	if err != nil {
		return nil, err
	}
	return warmpool.PutFile(ctx, base, req, sandboxFileTimeout)
}

// SandboxFileGet reads a file from the task's live sandbox filesystem.
func (k *KubernetesBackend) SandboxFileGet(ctx context.Context, workspaceID, taskID, path string) (*warmpool.FileGetResponse, error) {
	base, err := k.taskPodBaseURL(ctx, taskID)
	if err != nil {
		return nil, err
	}
	return warmpool.GetFile(ctx, base, workspaceID, taskID, path, sandboxFileTimeout)
}

// SandboxFileList lists regular files under prefix in the task's live sandbox.
func (k *KubernetesBackend) SandboxFileList(ctx context.Context, workspaceID, taskID, prefix string) (*warmpool.FileListResponse, error) {
	base, err := k.taskPodBaseURL(ctx, taskID)
	if err != nil {
		return nil, err
	}
	return warmpool.ListFiles(ctx, base, workspaceID, taskID, prefix, sandboxFileTimeout)
}
