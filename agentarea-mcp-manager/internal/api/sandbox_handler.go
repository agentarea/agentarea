package api

import (
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	corev1 "k8s.io/api/core/v1"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/features"
	"github.com/agentarea/mcp-manager/internal/warmpool"
)

// executeSandbox handles script execution requests through AgentArea's
// sandbox control plane. Production execution is intentionally routed through
// the Kubernetes warm-pool data plane; there is no direct executor URL
// fallback. Future customer-hosted executors should plug in as data-plane
// runners via a durable job/event protocol, not as ad-hoc HTTP fallbacks.
func (h *Handler) executeSandbox(c *gin.Context) {
	var req warmpool.ExecuteRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error":   "invalid_request",
			"message": err.Error(),
		})
		return
	}

	if req.ScriptContent == "" || req.ScriptName == "" {
		c.JSON(http.StatusBadRequest, gin.H{
			"error":   "invalid_request",
			"message": "script_content and script_name are required",
		})
		return
	}

	if !features.IsEnabled(features.WarmPool) {
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"error":   "sandbox_unavailable",
			"message": "sandbox warm pool is not enabled",
		})
		return
	}
	k8sBackend, ok := h.backend.(*backends.KubernetesBackend)
	if !ok {
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"error":   "sandbox_unavailable",
			"message": "sandbox requires Kubernetes backend",
		})
		return
	}
	wpClient := k8sBackend.GetWarmPoolClient()
	if wpClient == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"error":   "sandbox_unavailable",
			"message": "sandbox warm pool client is not available",
		})
		return
	}

	// When workflow_id is set, route every call to the same pod so
	// /workspace/wf-<id>/ persists across calls. When empty, use any waiting
	// pod for a stateless sandbox call.
	var pod *corev1.Pod
	var err error
	if req.WorkflowID != "" {
		pod, err = wpClient.FindOrAssignPodForWorkflow(c.Request.Context(), req.WorkflowID)
	} else {
		pod, err = wpClient.FindAvailablePod(c.Request.Context())
	}
	if err != nil {
		h.logger.Error("Sandbox warm pool assignment failed", "workflow_id", req.WorkflowID, "error", err)
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"error":   "sandbox_unavailable",
			"message": err.Error(),
		})
		return
	}
	result, err := wpClient.ExecuteInPod(c.Request.Context(), pod, req)
	if err != nil {
		h.logger.Error("Sandbox warm pool execution failed", "pod", pod.Name, "workflow_id", req.WorkflowID, "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error":   "execution_failed",
			"message": err.Error(),
		})
		return
	}
	c.Header("X-AgentArea-Sandbox-Backend", "agentarea-k8s")
	c.JSON(http.StatusOK, result)
}

// deleteSandboxWorkflow retires the sandbox state for a finished workflow.
// In K8s production it marks the workflow pod idle and schedules deletion after
// SANDBOX_WORKFLOW_IDLE_TTL; the GC loop performs the actual delete.
func (h *Handler) deleteSandboxWorkflow(c *gin.Context) {
	workflowID := c.Param("id")
	if workflowID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_request", "message": "workflow id is required"})
		return
	}

	if !features.IsEnabled(features.WarmPool) {
		c.Status(http.StatusNoContent)
		return
	}
	k8sBackend, ok := h.backend.(*backends.KubernetesBackend)
	if !ok {
		c.Status(http.StatusNoContent)
		return
	}
	wpClient := k8sBackend.GetWarmPoolClient()
	if wpClient == nil {
		c.Status(http.StatusNoContent)
		return
	}

	idleTTL := sandboxWorkflowIdleTTL()
	if c.Query("force") == "true" {
		idleTTL = 0
	}
	if err := wpClient.RetirePodForWorkflow(c.Request.Context(), workflowID, idleTTL); err != nil {
		h.logger.Error("warm pool pod retire failed", "workflow_id", workflowID, "idle_ttl", idleTTL, "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "cleanup_failed", "message": err.Error()})
		return
	}
	c.Status(http.StatusNoContent)
}

func sandboxWorkflowIdleTTL() time.Duration {
	raw := os.Getenv("SANDBOX_WORKFLOW_IDLE_TTL")
	if raw == "" {
		return 15 * time.Minute
	}
	if duration, err := time.ParseDuration(raw); err == nil && duration >= 0 {
		return duration
	}
	if seconds, err := strconv.Atoi(raw); err == nil && seconds >= 0 {
		return time.Duration(seconds) * time.Second
	}
	return 15 * time.Minute
}
