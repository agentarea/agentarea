package httpapi

import (
	"crypto/sha256"
	"crypto/subtle"
	"net/http"
	"strings"
)

// deleteSandboxTask retires the sandbox state for a finished task. In K8s it
// marks the task pod idle and schedules deletion after AGENTAREA_SANDBOX_IDLE_TTL;
// the GC loop performs the actual delete.
func (h *Handler) deleteSandboxTask(c *reqctx) {
	if !sandboxCleanupAuthorized(c.GetHeader("Authorization"), h.secrets.Cleanup) {
		c.JSON(http.StatusUnauthorized, jsonObject{"error": "unauthorized", "message": "valid cleanup bearer token is required"})
		return
	}

	taskID := c.Param("id")
	workspaceID := c.Query("workspace_id")
	if taskID == "" || workspaceID == "" {
		c.JSON(http.StatusBadRequest, jsonObject{"error": "invalid_request", "message": "workspace_id and task id are required"})
		return
	}

	idleTTL := h.sandboxPolicy.TaskIdleTTL
	if idleTTL < 0 {
		c.JSON(http.StatusServiceUnavailable, jsonObject{"error": "sandbox_policy_unavailable", "message": "sandbox task idle TTL is not configured"})
		return
	}
	if c.Query("force") == "true" {
		idleTTL = 0
	}
	if err := h.sandboxRuntime.RetireSandboxTask(c.Request.Context(), workspaceID, taskID, idleTTL); err != nil {
		h.logger.Error("sandbox task retire failed", "task_id", taskID, "idle_ttl", idleTTL, "error", err)
		c.JSON(http.StatusInternalServerError, jsonObject{"error": "cleanup_failed", "message": err.Error()})
		return
	}
	c.Status(http.StatusNoContent)
}

func sandboxCleanupAuthorized(authorizationHeader, expectedSecret string) bool {
	if expectedSecret == "" {
		return false
	}
	const prefix = "Bearer "
	if !strings.HasPrefix(authorizationHeader, prefix) {
		return false
	}
	presentedSecret := strings.TrimPrefix(authorizationHeader, prefix)
	if presentedSecret == "" {
		return false
	}
	expectedDigest := sha256.Sum256([]byte(expectedSecret))
	presentedDigest := sha256.Sum256([]byte(presentedSecret))
	return subtle.ConstantTimeCompare(presentedDigest[:], expectedDigest[:]) == 1
}
