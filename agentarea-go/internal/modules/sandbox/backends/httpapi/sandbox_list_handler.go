package httpapi

import (
	"net/http"
	"os"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/backends/sandboxruntime"
)

const sandboxInspectionAuthSecretEnv = "AGENTAREA_SANDBOX_INSPECT_SECRET"

func (h *Handler) listSandboxes(c *reqctx) {
	if !sandboxCleanupAuthorized(c.GetHeader("Authorization"), os.Getenv(sandboxInspectionAuthSecretEnv)) {
		c.JSON(http.StatusUnauthorized, jsonObject{
			"error":   "unauthorized",
			"message": "valid internal bearer token is required",
		})
		return
	}
	workspaceID := c.Query("workspace_id")
	if workspaceID == "" {
		c.JSON(http.StatusBadRequest, jsonObject{
			"error":   "invalid_request",
			"message": "workspace_id is required",
		})
		return
	}
	lister, ok := h.sandboxRuntime.(sandboxruntime.SandboxLister)
	if !ok {
		c.JSON(http.StatusServiceUnavailable, jsonObject{
			"error":   "sandbox_inventory_unavailable",
			"message": "configured sandbox runtime does not expose inventory",
		})
		return
	}
	sandboxes, err := lister.ListSandboxes(c.Request.Context(), workspaceID)
	if err != nil {
		h.logger.Error("sandbox inventory failed", "workspace_id", workspaceID, "error", err)
		c.JSON(http.StatusInternalServerError, jsonObject{
			"error":   "sandbox_inventory_failed",
			"message": err.Error(),
		})
		return
	}
	c.JSON(http.StatusOK, jsonObject{
		"items": sandboxes,
		"total": len(sandboxes),
	})
}
