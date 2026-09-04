package api

import (
	"net/http"
	"os"

	"github.com/agentarea/mcp-manager/internal/sandboxruntime"
	"github.com/gin-gonic/gin"
)

const sandboxInspectionAuthSecretEnv = "SANDBOX_INSPECTION_AUTH_SECRET"

func (h *Handler) listSandboxes(c *gin.Context) {
	if !sandboxCleanupAuthorized(c.GetHeader("Authorization"), os.Getenv(sandboxInspectionAuthSecretEnv)) {
		c.JSON(http.StatusUnauthorized, gin.H{
			"error":   "unauthorized",
			"message": "valid internal bearer token is required",
		})
		return
	}
	workspaceID := c.Query("workspace_id")
	if workspaceID == "" {
		c.JSON(http.StatusBadRequest, gin.H{
			"error":   "invalid_request",
			"message": "workspace_id is required",
		})
		return
	}
	lister, ok := h.sandboxRuntime.(sandboxruntime.SandboxLister)
	if !ok {
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"error":   "sandbox_inventory_unavailable",
			"message": "configured sandbox runtime does not expose inventory",
		})
		return
	}
	sandboxes, err := lister.ListSandboxes(c.Request.Context(), workspaceID)
	if err != nil {
		h.logger.Error("sandbox inventory failed", "workspace_id", workspaceID, "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error":   "sandbox_inventory_failed",
			"message": err.Error(),
		})
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"items": sandboxes,
		"total": len(sandboxes),
	})
}
