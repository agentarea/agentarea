package api

import (
	"crypto/sha256"
	"crypto/subtle"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/features"
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
	if taskID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_request", "message": "task id is required"})
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

	idleTTL := sandboxTaskIdleTTL()
	if c.Query("force") == "true" {
		idleTTL = 0
	}
	if err := wpClient.RetirePodForTask(c.Request.Context(), taskID, idleTTL); err != nil {
		h.logger.Error("warm pool pod retire failed", "task_id", taskID, "idle_ttl", idleTTL, "error", err)
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

func sandboxTaskIdleTTL() time.Duration {
	raw := os.Getenv("SANDBOX_TASK_IDLE_TTL")
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
