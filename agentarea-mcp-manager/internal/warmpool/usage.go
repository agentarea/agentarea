package warmpool

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/agentarea/mcp-manager/internal/usage"
	"github.com/google/uuid"
	corev1 "k8s.io/api/core/v1"
	k8serrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// SetUsageRecorder installs a trusted control-plane sink before serving work.
func (c *Client) SetUsageRecorder(recorder usage.Recorder) { c.usageRecorder = recorder }

func (c *Client) recordPodAllocation(ctx context.Context, pod *corev1.Pod) error {
	if c.usageRecorder == nil {
		return nil
	}
	if pod.UID == "" {
		return fmt.Errorf("sandbox usage requires pod UID for %s", pod.Name)
	}
	started, err := time.Parse(time.RFC3339, pod.Annotations[annotationTaskAssignedAt])
	if err != nil {
		return fmt.Errorf("sandbox usage requires assignment timestamp for %s: %w", pod.Name, err)
	}
	identity := sha256.Sum256([]byte(string(pod.UID)))
	containers := make(map[string]corev1.ResourceRequirements, len(pod.Spec.Containers))
	for _, container := range pod.Spec.Containers {
		containers[container.Name] = container.Resources
	}
	initContainers := make(map[string]corev1.ResourceRequirements, len(pod.Spec.InitContainers))
	for _, container := range pod.Spec.InitContainers {
		initContainers[container.Name] = container.Resources
	}
	return c.recordPodUsage(ctx, pod, "sandbox.allocated", "allocation-"+hex.EncodeToString(identity[:]), started, map[string]any{
		"provider": "kubernetes", "started_at": started, "measurement_status": "lifecycle_only",
		"container_resources": containers, "init_container_resources": initContainers,
		"pod_overhead": pod.Spec.Overhead, "resources_source": "kubernetes_pod_spec",
	})
}

func (c *Client) recordPodLease(ctx context.Context, pod *corev1.Pod) error {
	if c.usageRecorder == nil {
		return nil
	}
	if err := c.recordPodAllocation(ctx, pod); err != nil {
		return err
	}
	expiry := pod.Annotations[annotationTaskLeaseUntil]
	if pod.Labels[labelStatus] == statusIdle {
		expiry = pod.Annotations[annotationTaskCleanupAt]
	}
	return c.recordPodUsage(ctx, pod, "sandbox.lease_renewed", uuid.NewString(), time.Now().UTC(), map[string]any{
		"provider": "kubernetes", "expires_at": expiry, "expiry_is_intended": true, "state": pod.Labels[labelStatus],
	})
}

func (c *Client) recordPodUsage(ctx context.Context, pod *corev1.Pod, kind, id string, observed time.Time, data map[string]any) error {
	if c.usageRecorder == nil {
		return nil
	}
	encoded, err := json.Marshal(data)
	if err != nil {
		return err
	}
	event := usage.Event{
		SchemaVersion: usage.SchemaVersion,
		ID:            id, Source: "sandbox-kubernetes", Kind: kind,
		WorkspaceID: pod.Annotations[annotationWorkspaceID], TaskID: pod.Annotations[annotationTaskID],
		ResourceKind: "sandbox", ResourceID: pod.Namespace + "/" + pod.Name,
		IncarnationID: string(pod.UID), OccurredAt: observed, Data: encoded,
	}
	if err := c.usageRecorder.Record(ctx, event); err != nil {
		return fmt.Errorf("record sandbox usage %s %s for pod %s/%s: %w", kind, id, pod.Name, pod.UID, err)
	}
	return nil
}

func (c *Client) deletePodWithUsage(ctx context.Context, pod *corev1.Pod, options metav1.DeleteOptions, reason string) error {
	if c.usageRecorder == nil {
		return c.client.CoreV1().Pods(c.namespace).Delete(ctx, pod.Name, options)
	}
	allocationErr := c.recordPodAllocation(ctx, pod)
	attempt := uuid.NewString()
	requestErr := c.recordPodUsage(ctx, pod, "sandbox.delete_requested", attempt+"-request", time.Now().UTC(), map[string]any{
		"provider": "kubernetes", "reason": reason, "termination_confirmed": false,
	})
	deleteErr := c.client.CoreV1().Pods(c.namespace).Delete(ctx, pod.Name, options)
	kind := "sandbox.delete_accepted"
	confirmed := false
	if k8serrors.IsNotFound(deleteErr) {
		kind = "sandbox.missing"
		confirmed = true
	} else if deleteErr != nil {
		kind = "sandbox.delete_failed"
	}
	outcomeCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 15*time.Second)
	defer cancel()
	outcomeErr := c.recordPodUsage(outcomeCtx, pod, kind, attempt+"-outcome", time.Now().UTC(), map[string]any{
		"provider": "kubernetes", "reason": reason, "termination_confirmed": confirmed,
	})
	if allocationErr != nil || requestErr != nil || outcomeErr != nil {
		// Do not let callers normalize NotFound/Conflict and hide a recording failure.
		return fmt.Errorf("sandbox deletion outcome: %v; usage: %w", deleteErr, errors.Join(allocationErr, requestErr, outcomeErr))
	}
	return deleteErr
}
