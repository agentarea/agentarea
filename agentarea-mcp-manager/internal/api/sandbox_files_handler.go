package api

import (
	"encoding/hex"
	"errors"
	"io/fs"
	"net/http"
	"os"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/agentarea/mcp-manager/internal/sandboxruntime"
	"github.com/agentarea/mcp-manager/internal/warmpool"
)

const sandboxFileAuthSecretEnv = "SANDBOX_FILE_AUTH_SECRET"

// sandboxFiles proxies the sandbox file API to the executor data plane. The file
// tool writes here so its files land on the same filesystem bash executes in,
// instead of the S3 task workspace bash cannot see. The control plane signs the
// ScopeFiles token; the activation secret never reaches the worker.
func (h *Handler) sandboxFiles(c *gin.Context) {
	if !requireSandboxFileAuthorization(c) {
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
		result, err := h.sandboxRuntime.PutWorkspaceFile(c.Request.Context(), req)
		if err != nil {
			h.logger.Error("sandbox file put failed", "task_id", req.TaskID, "error", err)
			c.JSON(http.StatusBadGateway, gin.H{"error": "file_put_failed", "message": err.Error()})
			return
		}
		c.JSON(http.StatusOK, result)

	case http.MethodGet:
		workspaceID := c.Query("workspace_id")
		taskID := c.Query("task_id")
		ensure := c.Query("ensure") != "false"
		if workspaceID == "" || taskID == "" {
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_request", "message": "workspace_id and task_id are required"})
			return
		}
		demand := sandboxruntime.WorkspaceFileDemand{
			WorkspaceID: workspaceID, TaskID: taskID, Ensure: ensure,
		}
		if prefix, listing := c.GetQuery("list"); listing {
			result, err := h.sandboxRuntime.ListWorkspaceFiles(c.Request.Context(), sandboxruntime.WorkspaceFileList{
				WorkspaceFileDemand: demand, Prefix: prefix,
			})
			if err != nil {
				if errors.Is(err, sandboxruntime.ErrSessionNotFound) || errors.Is(err, warmpool.ErrTaskPodNotFound) || errors.Is(err, warmpool.ErrTaskWorkspaceGone) {
					c.JSON(http.StatusGone, gin.H{"error": "sandbox_expired"})
					return
				}
				h.logger.Error("sandbox file list failed", "task_id", taskID, "error", err)
				c.JSON(http.StatusBadGateway, gin.H{"error": "file_list_failed", "message": err.Error()})
				return
			}
			visible := result.Paths[:0]
			for _, path := range result.Paths {
				if path == ".agentarea" || strings.HasPrefix(path, ".agentarea/") {
					continue
				}
				visible = append(visible, path)
			}
			result.Paths = visible
			c.JSON(http.StatusOK, result)
			return
		}
		result, err := h.sandboxRuntime.GetWorkspaceFile(c.Request.Context(), sandboxruntime.WorkspaceFileRead{
			WorkspaceFileDemand: demand, Path: c.Query("path"),
		})
		if err != nil {
			if errors.Is(err, sandboxruntime.ErrSessionNotFound) || errors.Is(err, warmpool.ErrTaskPodNotFound) || errors.Is(err, warmpool.ErrTaskWorkspaceGone) {
				c.JSON(http.StatusGone, gin.H{"error": "sandbox_expired"})
				return
			}
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

// sandboxFileContent is the raw streaming counterpart to /sandbox/files. It is
// used by current clients for file bodies while the JSON endpoint remains only
// as a bounded compatibility surface.
func (h *Handler) sandboxFileContent(c *gin.Context) {
	if !requireSandboxFileAuthorization(c) {
		return
	}
	maxBytes := h.sandboxPolicy.MaxFileBytes
	if maxBytes <= 0 {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "sandbox_policy_unavailable", "message": "sandbox file quota is not configured"})
		return
	}
	switch c.Request.Method {
	case http.MethodPut:
		workspaceID := c.Query("workspace_id")
		taskID := c.Query("task_id")
		filePath := c.Query("path")
		size, sizeErr := strconv.ParseInt(c.Query("size"), 10, 64)
		mode, modeErr := strconv.ParseUint(c.Query("mode"), 8, 32)
		sha256Hex := c.Query("sha256")
		digest, digestErr := hex.DecodeString(sha256Hex)
		if workspaceID == "" || taskID == "" || filePath == "" || sizeErr != nil || size < 0 || size > maxBytes || modeErr != nil || mode == 0 || mode&^uint64(0o777) != 0 || digestErr != nil || len(digest) != 32 || sha256Hex != strings.ToLower(sha256Hex) {
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_request", "message": "workspace_id, task_id, path, admitted size, mode, and lowercase sha256 are required"})
			return
		}
		if c.Request.ContentLength != size {
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_request", "message": "Content-Length does not match size"})
			return
		}
		result, err := h.sandboxRuntime.UploadWorkspaceFile(c.Request.Context(), sandboxruntime.FileUpload{
			WorkspaceID: workspaceID, TaskID: taskID,
			Path: filePath, Size: size, SHA256: sha256Hex, Mode: fs.FileMode(mode),
		}, c.Request.Body)
		if err != nil {
			h.logger.Error("streamed sandbox file put failed", "task_id", taskID, "error", err)
			c.JSON(http.StatusBadGateway, gin.H{"error": "file_put_failed", "message": err.Error()})
			return
		}
		c.JSON(http.StatusOK, result)

	case http.MethodGet:
		workspaceID := c.Query("workspace_id")
		taskID := c.Query("task_id")
		ensure := c.Query("ensure") != "false"
		if workspaceID == "" || taskID == "" {
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_request", "message": "workspace_id and task_id are required"})
			return
		}
		download, err := h.sandboxRuntime.OpenWorkspaceFile(c.Request.Context(), sandboxruntime.WorkspaceFileRead{
			WorkspaceFileDemand: sandboxruntime.WorkspaceFileDemand{
				WorkspaceID: workspaceID, TaskID: taskID, Ensure: ensure,
			},
			Path: c.Query("path"),
		})
		if err != nil {
			if errors.Is(err, sandboxruntime.ErrSessionNotFound) || errors.Is(err, warmpool.ErrTaskPodNotFound) || errors.Is(err, warmpool.ErrTaskWorkspaceGone) {
				c.JSON(http.StatusGone, gin.H{"error": "sandbox_expired"})
				return
			}
			if errors.Is(err, warmpool.ErrFileNotFound) {
				c.JSON(http.StatusNotFound, gin.H{"error": "not_found"})
				return
			}
			c.JSON(http.StatusBadGateway, gin.H{"error": "file_get_failed", "message": err.Error()})
			return
		}
		defer download.Content.Close()
		if download.Size > maxBytes {
			c.JSON(http.StatusRequestEntityTooLarge, gin.H{"error": "workspace_file_quota_exceeded", "limit": maxBytes})
			return
		}
		c.DataFromReader(http.StatusOK, download.Size, "application/octet-stream", download.Content, nil)

	default:
		c.JSON(http.StatusMethodNotAllowed, gin.H{"error": "method_not_allowed"})
	}
}

func requireSandboxFileAuthorization(c *gin.Context) bool {
	if sandboxCleanupAuthorized(c.GetHeader("Authorization"), os.Getenv(sandboxFileAuthSecretEnv)) {
		return true
	}
	c.JSON(http.StatusUnauthorized, gin.H{
		"error":   "unauthorized",
		"message": "valid internal sandbox file bearer token is required",
	})
	return false
}
