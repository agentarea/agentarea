package api

import (
	"context"
	"errors"
	"net/http"

	"github.com/gin-gonic/gin"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/warmpool"
)

// sandboxFilesProvider is the subset of a backend that can operate on a task's
// sandbox file workspace. Both shipped backends implement it: docker against
// SANDBOX_EXECUTOR_URL, Kubernetes against the task's already-assigned pod.
type sandboxFilesProvider interface {
	SandboxFilePut(ctx context.Context, req warmpool.FilePutRequest) (*warmpool.FilePutResponse, error)
	SandboxFileGet(ctx context.Context, workspaceID, taskID, path string) (*warmpool.FileGetResponse, error)
	SandboxFileList(ctx context.Context, workspaceID, taskID, prefix string) (*warmpool.FileListResponse, error)
}

// The 503 below is reached by type assertion, so a backend that quietly stops
// satisfying this interface degrades at runtime instead of failing to build.
// These make that a compile error — the file tool and bash must see the same
// filesystem on every substrate, not just the one someone tested.
var (
	_ sandboxFilesProvider = (*backends.DockerBackend)(nil)
	_ sandboxFilesProvider = (*backends.KubernetesBackend)(nil)
)

// sandboxFiles proxies the sandbox file API to the executor data plane. The file
// tool writes here so its files land on the same filesystem bash executes in,
// instead of the S3 task workspace bash cannot see. The control plane signs the
// ScopeFiles token; the activation secret never reaches the worker.
func (h *Handler) sandboxFiles(c *gin.Context) {
	provider, ok := h.backend.(sandboxFilesProvider)
	if !ok {
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"error":   "sandbox_files_unavailable",
			"message": "sandbox backend does not expose a file API",
		})
		return
	}

	switch c.Request.Method {
	case http.MethodPut:
		var req warmpool.FilePutRequest
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_request", "message": err.Error()})
			return
		}
		if req.WorkspaceID == "" || req.TaskID == "" {
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_request", "message": "workspace_id and task_id are required"})
			return
		}
		result, err := provider.SandboxFilePut(c.Request.Context(), req)
		if err != nil {
			h.logger.Error("sandbox file put failed", "task_id", req.TaskID, "error", err)
			c.JSON(http.StatusBadGateway, gin.H{"error": "file_put_failed", "message": err.Error()})
			return
		}
		c.JSON(http.StatusOK, result)

	case http.MethodGet:
		workspaceID := c.Query("workspace_id")
		taskID := c.Query("task_id")
		if workspaceID == "" || taskID == "" {
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_request", "message": "workspace_id and task_id are required"})
			return
		}
		if prefix, listing := c.GetQuery("list"); listing {
			result, err := provider.SandboxFileList(c.Request.Context(), workspaceID, taskID, prefix)
			if err != nil {
				h.logger.Error("sandbox file list failed", "task_id", taskID, "error", err)
				c.JSON(http.StatusBadGateway, gin.H{"error": "file_list_failed", "message": err.Error()})
				return
			}
			c.JSON(http.StatusOK, result)
			return
		}
		result, err := provider.SandboxFileGet(c.Request.Context(), workspaceID, taskID, c.Query("path"))
		if err != nil {
			if errors.Is(err, warmpool.ErrFileNotFound) {
				c.JSON(http.StatusNotFound, gin.H{"error": "not_found"})
				return
			}
			h.logger.Error("sandbox file get failed", "task_id", taskID, "error", err)
			c.JSON(http.StatusBadGateway, gin.H{"error": "file_get_failed", "message": err.Error()})
			return
		}
		c.JSON(http.StatusOK, result)

	default:
		c.JSON(http.StatusMethodNotAllowed, gin.H{"error": "method_not_allowed"})
	}
}
