package api

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"strconv"

	"github.com/gin-gonic/gin"

	"github.com/agentarea/mcp-manager/internal/artifactstore"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime"
	"github.com/agentarea/mcp-manager/internal/warmpool"
)

type sandboxArtifactStore interface {
	PublishStream(context.Context, string, string, string, string, io.Reader, int64) (artifactstore.Artifact, error)
	List(context.Context, string, string) ([]artifactstore.Artifact, error)
	Open(context.Context, string, string, string) (artifactstore.Artifact, io.ReadCloser, error)
}

type publishSandboxArtifactRequest struct {
	WorkspaceID string `json:"workspace_id" binding:"required"`
	TaskID      string `json:"task_id" binding:"required"`
	Path        string `json:"path" binding:"required"`
	ContentType string `json:"content_type,omitempty"`
}

func (h *Handler) SetSandboxArtifactStore(store sandboxArtifactStore) {
	h.sandboxArtifacts = store
}

func (h *Handler) sandboxArtifactsCollection(c *gin.Context) {
	if !requireSandboxFileAuthorization(c) {
		return
	}
	if h.sandboxArtifacts == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "artifact_store_unavailable"})
		return
	}
	switch c.Request.Method {
	case http.MethodPost:
		h.publishSandboxArtifact(c)
	case http.MethodGet:
		h.listSandboxArtifacts(c)
	default:
		c.JSON(http.StatusMethodNotAllowed, gin.H{"error": "method_not_allowed"})
	}
}

func (h *Handler) publishSandboxArtifact(c *gin.Context) {
	var req publishSandboxArtifactRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_request", "message": err.Error()})
		return
	}
	file, err := h.sandboxRuntime.OpenWorkspaceFile(c.Request.Context(), sandboxruntime.WorkspaceFileRead{
		WorkspaceFileDemand: sandboxruntime.WorkspaceFileDemand{
			WorkspaceID: req.WorkspaceID,
			TaskID:      req.TaskID,
			Ensure:      false,
		},
		Path: req.Path,
	})
	if err != nil {
		if errors.Is(err, sandboxruntime.ErrSessionNotFound) || errors.Is(err, warmpool.ErrTaskPodNotFound) || errors.Is(err, warmpool.ErrTaskWorkspaceGone) {
			c.JSON(http.StatusGone, gin.H{"error": "sandbox_expired"})
			return
		}
		if errors.Is(err, warmpool.ErrFileNotFound) {
			c.JSON(http.StatusNotFound, gin.H{"error": "file_not_found"})
			return
		}
		c.JSON(http.StatusBadGateway, gin.H{"error": "file_read_failed", "message": err.Error()})
		return
	}
	defer file.Content.Close()
	artifact, err := h.sandboxArtifacts.PublishStream(c.Request.Context(), req.WorkspaceID, req.TaskID, req.Path, req.ContentType, file.Content, file.Size)
	if err != nil {
		if errors.Is(err, artifactstore.ErrArtifactQuotaExceeded) {
			c.JSON(http.StatusRequestEntityTooLarge, gin.H{"error": "artifact_quota_exceeded", "message": err.Error()})
			return
		}
		c.JSON(http.StatusBadGateway, gin.H{"error": "artifact_publish_failed", "message": err.Error()})
		return
	}
	c.JSON(http.StatusCreated, artifact)
}

func (h *Handler) listSandboxArtifacts(c *gin.Context) {
	workspaceID := c.Query("workspace_id")
	taskID := c.Query("task_id")
	if workspaceID == "" || taskID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "workspace_id and task_id are required"})
		return
	}
	items, err := h.sandboxArtifacts.List(c.Request.Context(), workspaceID, taskID)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "artifact_list_failed", "message": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"items": items})
}

func (h *Handler) getSandboxArtifact(c *gin.Context) {
	if !requireSandboxFileAuthorization(c) {
		return
	}
	if h.sandboxArtifacts == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "artifact_store_unavailable"})
		return
	}
	workspaceID := c.Query("workspace_id")
	taskID := c.Query("task_id")
	artifact, content, err := h.sandboxArtifacts.Open(c.Request.Context(), workspaceID, taskID, c.Param("id"))
	if errors.Is(err, artifactstore.ErrArtifactNotFound) {
		c.JSON(http.StatusNotFound, gin.H{"error": "artifact_not_found"})
		return
	}
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "artifact_read_failed", "message": err.Error()})
		return
	}
	defer content.Close()
	verified, err := stageVerifiedArtifact(content, artifact.Size)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "artifact_read_failed", "message": err.Error()})
		return
	}
	defer func() {
		name := verified.Name()
		_ = verified.Close()
		_ = os.Remove(name)
	}()
	contentType := artifact.ContentType
	if contentType == "" {
		contentType = "application/octet-stream"
	}
	c.Header("Content-Type", contentType)
	c.Header("Content-Length", strconv.FormatInt(artifact.Size, 10))
	c.Header("Content-Disposition", fmt.Sprintf(`attachment; filename=%q`, artifact.Name))
	c.DataFromReader(http.StatusOK, artifact.Size, contentType, verified, nil)
}

// stageVerifiedArtifact finishes the store's size and checksum verification
// before the HTTP response is committed. Streaming an EOF-verifying reader
// directly would allow a client to receive corrupt bytes under a 200 status.
func stageVerifiedArtifact(source io.Reader, expectedSize int64) (_ *os.File, resultErr error) {
	if expectedSize < 0 {
		return nil, fmt.Errorf("artifact has invalid size")
	}
	temp, err := os.CreateTemp("", "agentarea-artifact-download-*")
	if err != nil {
		return nil, fmt.Errorf("create verified artifact spool: %w", err)
	}
	defer func() {
		if resultErr != nil {
			name := temp.Name()
			_ = temp.Close()
			_ = os.Remove(name)
		}
	}()

	written, err := io.Copy(temp, io.LimitReader(source, expectedSize+1))
	if err != nil {
		return nil, fmt.Errorf("verify artifact body: %w", err)
	}
	if written != expectedSize {
		return nil, fmt.Errorf("artifact body size mismatch: got %d, expected %d", written, expectedSize)
	}
	if _, err := temp.Seek(0, io.SeekStart); err != nil {
		return nil, fmt.Errorf("rewind verified artifact spool: %w", err)
	}
	return temp, nil
}
