package api

import (
	"crypto/sha256"
	"crypto/subtle"
	"net/http"
	"os"
	"strings"

	"github.com/gin-gonic/gin"
)

const sandboxCleanupAuthSecretEnv = "SANDBOX_CLEANUP_AUTH_SECRET"

// deleteSandboxTask retires the sandbox state for a finished task. In K8s it
// marks the task pod idle and schedules deletion after SANDBOX_TASK_IDLE_TTL;
// the GC loop performs the actual delete.
func (h *Handler) deleteSandboxTask(c *gin.Context) {
	if !sandboxCleanupAuthorized(c.GetHeader("Authorization"), os.Getenv(sandboxCleanupAuthSecretEnv)) {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized", "message": "valid cleanup bearer token is required"})
		return
	}

	taskID := c.Param("id")
	workspaceID := c.Query("workspace_id")
	if taskID == "" || workspaceID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_request", "message": "workspace_id and task id are required"})
		return
	}

	idleTTL := h.sandboxPolicy.TaskIdleTTL
	if idleTTL < 0 {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "sandbox_policy_unavailable", "message": "sandbox task idle TTL is not configured"})
		return
	}
	if c.Query("force") == "true" {
		idleTTL = 0
	}
	if err := h.sandboxRuntime.RetireSandboxTask(c.Request.Context(), workspaceID, taskID, idleTTL); err != nil {
		h.logger.Error("sandbox task retire failed", "task_id", taskID, "idle_ttl", idleTTL, "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "cleanup_failed", "message": err.Error()})
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
