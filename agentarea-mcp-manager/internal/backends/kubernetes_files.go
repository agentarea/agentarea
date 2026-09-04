package backends

import (
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"sync"
	"time"

	corev1 "k8s.io/api/core/v1"

	"github.com/agentarea/mcp-manager/internal/sandboxruntime"
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
// Reads route only to the task's existing pod. A write may be the first demand
// signal and assigns from the configured runtime pool. After assignment all
// file operations stay pinned to that pod.

const sandboxFileTimeout = 30 * time.Second

// taskPod either resolves the existing task pod or assigns one for a write.
// Read/list never create a replacement; a task with no live pod is reported as
// expired instead of silently recreated.
func (k *KubernetesBackend) taskPod(ctx context.Context, workspaceID, taskID string, assign bool) (*warmpool.Client, *corev1.Pod, string, string, error) {
	if workspaceID == "" {
		return nil, nil, "", "", fmt.Errorf("workspace_id is required for sandbox file access")
	}
	if taskID == "" {
		return nil, nil, "", "", fmt.Errorf("task_id is required for sandbox file access")
	}
	wp := k.GetWarmPoolClient()
	if wp == nil {
		return nil, nil, "", "", fmt.Errorf("warm pool client unavailable")
	}
	var pod *corev1.Pod
	var err error
	if scope, ok := operationScope(ctx); ok && scope.bound() {
		pod, _, err = scope.pod(ctx)
	} else if assign {
		pod, err = wp.FindOrAssignPodForTask(ctx, workspaceID, taskID)
	} else {
		pod, err = wp.FindPodForTask(ctx, workspaceID, taskID)
	}
	if err != nil {
		return nil, nil, "", "", err
	}
	pod, incarnation, err := wp.VerifyOrBindExecutorIncarnation(ctx, pod)
	if err != nil {
		return nil, nil, "", "", err
	}
	base, err := podActivationURL(pod)
	return wp, pod, base, incarnation, err
}

func podActivationURL(pod *corev1.Pod) (string, error) {
	if pod.Status.PodIP == "" {
		return "", fmt.Errorf("sandbox pod %s has no IP address yet", pod.Name)
	}
	return fmt.Sprintf("http://%s:8080", pod.Status.PodIP), nil
}

// SandboxFilePut writes a file into the task's live sandbox filesystem.
func (k *KubernetesBackend) SandboxFilePut(ctx context.Context, req warmpool.FilePutRequest) (*warmpool.FilePutResponse, error) {
	wp, pod, base, incarnation, err := k.taskPod(ctx, req.WorkspaceID, req.TaskID, true)
	if err != nil {
		return nil, err
	}
	var result *warmpool.FilePutResponse
	req.ExecutorIncarnation = incarnation
	err = k.withPodLease(ctx, wp, pod, func(operationCtx context.Context) error {
		var operationErr error
		result, operationErr = warmpool.PutFile(operationCtx, base, req, sandboxFileTimeout)
		return operationErr
	})
	return result, k.invalidateUnsafePod(ctx, wp, pod, err)
}

func (k *KubernetesBackend) SandboxFileUpload(ctx context.Context, req sandboxruntime.FileUpload, content io.Reader) (*sandboxruntime.FileWriteResult, error) {
	wp, pod, base, incarnation, err := k.taskPod(ctx, req.WorkspaceID, req.TaskID, true)
	if err != nil {
		return nil, err
	}
	var result *warmpool.FilePutResponse
	err = k.withPodLease(ctx, wp, pod, func(operationCtx context.Context) error {
		var operationErr error
		result, operationErr = warmpool.PutFileStream(operationCtx, base, warmpool.FileTransferRequest{
			WorkspaceID: req.WorkspaceID, TaskID: req.TaskID,
			ExecutorIncarnation: incarnation, Path: req.Path, Size: req.Size, SHA256: req.SHA256, Mode: uint32(req.Mode),
		}, content, 10*time.Minute)
		return operationErr
	})
	err = k.invalidateUnsafePod(ctx, wp, pod, err)
	if err != nil {
		return nil, err
	}
	return &sandboxruntime.FileWriteResult{Path: result.Path, Size: result.Size}, nil
}

// SandboxFileGet reads a file from the task's live sandbox filesystem.
func (k *KubernetesBackend) SandboxFileGet(ctx context.Context, workspaceID, taskID, path string) (*warmpool.FileGetResponse, error) {
	wp, pod, base, incarnation, err := k.taskPod(ctx, workspaceID, taskID, false)
	if err != nil {
		return nil, err
	}
	var result *warmpool.FileGetResponse
	err = k.withPodLease(ctx, wp, pod, func(operationCtx context.Context) error {
		var operationErr error
		result, operationErr = warmpool.GetFileForIncarnation(operationCtx, base, workspaceID, taskID, path, incarnation, sandboxFileTimeout)
		return operationErr
	})
	return result, k.invalidateUnsafePod(ctx, wp, pod, err)
}

func (k *KubernetesBackend) SandboxFileDownload(ctx context.Context, workspaceID, taskID, path string) (*sandboxruntime.FileDownload, error) {
	wp, pod, base, incarnation, err := k.taskPod(ctx, workspaceID, taskID, false)
	if err != nil {
		return nil, err
	}
	leaseCtx, heartbeat, err := k.startPodLease(ctx, wp, pod)
	if err != nil {
		return nil, err
	}
	result, err := warmpool.OpenFileForIncarnation(leaseCtx, base, workspaceID, taskID, path, incarnation, 10*time.Minute)
	if err != nil {
		leaseErr := heartbeat.stop()
		return nil, k.invalidateUnsafePod(ctx, wp, pod, errors.Join(err, leaseErr))
	}
	return &sandboxruntime.FileDownload{Content: &podLeaseReadCloser{source: result.Content, heartbeat: heartbeat}, Size: result.Size, Mode: fs.FileMode(result.Mode)}, nil
}

// SandboxFileList lists regular files under prefix in the task's live sandbox.
func (k *KubernetesBackend) SandboxFileList(ctx context.Context, workspaceID, taskID, prefix string) (*warmpool.FileListResponse, error) {
	wp, pod, base, incarnation, err := k.taskPod(ctx, workspaceID, taskID, false)
	if err != nil {
		return nil, err
	}
	var result *warmpool.FileListResponse
	err = k.withPodLease(ctx, wp, pod, func(operationCtx context.Context) error {
		var operationErr error
		result, operationErr = warmpool.ListFilesForIncarnation(operationCtx, base, workspaceID, taskID, prefix, incarnation, sandboxFileTimeout)
		return operationErr
	})
	return result, k.invalidateUnsafePod(ctx, wp, pod, err)
}

type podLeaseHeartbeat struct {
	stopOnce  sync.Once
	stopCh    chan struct{}
	done      chan error
	cancel    context.CancelFunc
	client    *warmpool.Client
	operation *warmpool.TaskOperation
	stopErr   error
}

func (k *KubernetesBackend) startPodLease(ctx context.Context, client *warmpool.Client, pod *corev1.Pod) (context.Context, *podLeaseHeartbeat, error) {
	operation, err := client.BeginTaskOperation(ctx, pod, k.taskLeaseTTL)
	if err != nil {
		return nil, nil, fmt.Errorf("register sandbox pod operation: %w", err)
	}
	leaseCtx, cancel := context.WithCancel(ctx)
	heartbeat := &podLeaseHeartbeat{
		stopCh: make(chan struct{}), done: make(chan error, 1), cancel: cancel,
		client: client, operation: operation,
	}
	interval := k.taskLeaseTTL / 3
	if interval <= 0 {
		interval = k.taskLeaseTTL
	}
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for {
			select {
			case <-heartbeat.stopCh:
				heartbeat.done <- nil
				return
			case <-leaseCtx.Done():
				heartbeat.done <- leaseCtx.Err()
				return
			case <-ticker.C:
				if err := client.TouchTaskOperation(leaseCtx, operation, k.taskLeaseTTL); err != nil {
					heartbeat.done <- err
					cancel()
					return
				}
			}
		}
	}()
	return leaseCtx, heartbeat, nil
}

func (h *podLeaseHeartbeat) stop() error {
	h.stopOnce.Do(func() {
		close(h.stopCh)
		heartbeatErr := <-h.done
		h.cancel()
		if errors.Is(heartbeatErr, context.Canceled) {
			heartbeatErr = nil
		}
		endCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		endErr := h.client.EndTaskOperation(endCtx, h.operation)
		h.stopErr = errors.Join(heartbeatErr, endErr)
	})
	return h.stopErr
}

func (k *KubernetesBackend) withPodLease(ctx context.Context, client *warmpool.Client, pod *corev1.Pod, operation func(context.Context) error) error {
	leaseCtx, heartbeat, err := k.startPodLease(ctx, client, pod)
	if err != nil {
		return err
	}
	operationErr := operation(leaseCtx)
	heartbeatErr := heartbeat.stop()
	if heartbeatErr == nil {
		return operationErr
	}
	return errors.Join(operationErr, fmt.Errorf("sandbox pod lease heartbeat failed: %w", heartbeatErr))
}

type podLeaseReadCloser struct {
	source    io.ReadCloser
	heartbeat *podLeaseHeartbeat
	stopOnce  sync.Once
	stopErr   error
}

func (r *podLeaseReadCloser) Read(buffer []byte) (int, error) {
	n, err := r.source.Read(buffer)
	if err != nil {
		r.finish()
		if r.stopErr != nil {
			return n, fmt.Errorf("sandbox pod lease heartbeat failed: %w", r.stopErr)
		}
	}
	return n, err
}

func (r *podLeaseReadCloser) Close() error {
	sourceErr := r.source.Close()
	r.finish()
	if r.stopErr != nil {
		return r.stopErr
	}
	return sourceErr
}

func (r *podLeaseReadCloser) finish() {
	r.stopOnce.Do(func() { r.stopErr = r.heartbeat.stop() })
}
