package httpapi

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/backends/sandboxcontrol"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/backends/sandboxcontrolauth"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/backends/warmpool"
)

const (
	sandboxWorkspaceHeader             = "X-Agentarea-Workspace-ID"
	sandboxTaskHeader                  = "X-Agentarea-Task-ID"
	maxSandboxExecutionCreateBodyBytes = int64(warmpool.MaxCommandBodyBytes + 64*1024)
)

// newSandboxControlService builds the execution-record service from the
// configuration the composition root already resolved. It reads no process
// environment of its own, so retention and admission policy cannot drift.
func newSandboxControlService(cfg sandboxcontrol.Config) (*sandboxcontrol.Service, error) {
	store, err := sandboxcontrol.NewRedisStoreFromConfig(cfg)
	if err != nil {
		return nil, fmt.Errorf("sandbox control store: %w", err)
	}
	service, err := sandboxcontrol.NewService(store, cfg.ExecutionPolicy())
	if err != nil {
		_ = store.Close()
		return nil, fmt.Errorf("sandbox control service: %w", err)
	}
	return service, nil
}

func (h *Handler) createSandboxExecution(c *reqctx) {
	if h.sandboxControl == nil {
		sandboxControlUnavailable(c)
		return
	}
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, maxSandboxExecutionCreateBodyBytes)
	body, err := io.ReadAll(c.Request.Body)
	if err != nil {
		c.JSON(http.StatusBadRequest, jsonObject{"error": "invalid_request", "message": "sandbox execution request body is invalid or too large"})
		return
	}
	var req sandboxcontrol.ExecutionCreateRequest
	if err := json.Unmarshal(body, &req); err != nil {
		c.JSON(http.StatusBadRequest, jsonObject{"error": "invalid_request", "message": err.Error()})
		return
	}
	if !requireSandboxControlAuthorization(c, sandboxcontrolauth.ScopeCreate, sandboxcontrolauth.Identity{
		WorkspaceID: req.WorkspaceID,
		TaskID:      req.TaskID,
	}, sandboxcontrolauth.BodySHA256(body)) {
		return
	}
	record, err := h.sandboxControl.CreateExecution(c.Request.Context(), req)
	if err != nil {
		h.writeSandboxControlError(c, "create", err)
		return
	}
	c.JSON(http.StatusAccepted, record)
}

func (h *Handler) getSandboxExecution(c *reqctx) {
	if h.sandboxControl == nil {
		sandboxControlUnavailable(c)
		return
	}
	identity := sandboxExecutionIdentity(c)
	if !requireSandboxControlAuthorization(c, sandboxcontrolauth.ScopeRead, identity, sandboxcontrolauth.BodySHA256(nil)) {
		return
	}
	record, err := h.sandboxControl.GetExecution(c.Request.Context(), c.Param("id"))
	if err != nil {
		h.writeSandboxControlError(c, "get", err)
		return
	}
	if record.WorkspaceID != identity.WorkspaceID || record.TaskID != identity.TaskID {
		c.JSON(http.StatusForbidden, jsonObject{"error": "workspace_scope_mismatch"})
		return
	}
	c.JSON(http.StatusOK, record)
}

func (h *Handler) cancelSandboxExecution(c *reqctx) {
	if h.sandboxControl == nil {
		sandboxControlUnavailable(c)
		return
	}
	identity := sandboxExecutionIdentity(c)
	if !requireSandboxControlAuthorization(c, sandboxcontrolauth.ScopeCancel, identity, sandboxcontrolauth.BodySHA256(nil)) {
		return
	}
	record, err := h.sandboxControl.GetExecution(c.Request.Context(), c.Param("id"))
	if err != nil {
		h.writeSandboxControlError(c, "cancel", err)
		return
	}
	if record.WorkspaceID != identity.WorkspaceID || record.TaskID != identity.TaskID {
		c.JSON(http.StatusForbidden, jsonObject{"error": "workspace_scope_mismatch"})
		return
	}
	record, err = h.sandboxControl.CancelExecution(c.Request.Context(), c.Param("id"), "execution caller stopped waiting")
	if err != nil {
		h.writeSandboxControlError(c, "cancel", err)
		return
	}
	c.JSON(http.StatusOK, record)
}

func sandboxExecutionIdentity(c *reqctx) sandboxcontrolauth.Identity {
	return sandboxcontrolauth.Identity{
		WorkspaceID: c.GetHeader(sandboxWorkspaceHeader),
		TaskID:      c.GetHeader(sandboxTaskHeader),
		ExecutionID: c.Param("id"),
	}
}

func requireSandboxControlAuthorization(c *reqctx, scope string, identity sandboxcontrolauth.Identity, bodySHA256 string) bool {
	token, err := sandboxcontrolauth.BearerToken(c.GetHeader("Authorization"))
	if err == nil {
		err = sandboxcontrolauth.VerifyFromEnv(token, scope, identity, bodySHA256, time.Now().UTC())
	}
	if err != nil {
		c.JSON(http.StatusUnauthorized, jsonObject{"error": "unauthorized", "message": "valid workspace-scoped sandbox control authorization is required"})
		return false
	}
	return true
}

func sandboxControlUnavailable(c *reqctx) {
	c.JSON(http.StatusServiceUnavailable, jsonObject{
		"error":   "sandbox_control_unavailable",
		"message": "sandbox control plane is not configured",
	})
}

func (h *Handler) writeSandboxControlError(c *reqctx, operation string, err error) {
	switch {
	case errors.Is(err, sandboxcontrol.ErrInvalidExecution):
		c.JSON(http.StatusBadRequest, jsonObject{"error": "invalid_request", "message": err.Error()})
	case errors.Is(err, sandboxcontrol.ErrExecutionNotFound):
		c.JSON(http.StatusNotFound, jsonObject{"error": "not_found"})
	case errors.Is(err, sandboxcontrol.ErrExecutionConflict):
		c.JSON(http.StatusConflict, jsonObject{"error": "execution_conflict", "message": err.Error()})
	default:
		h.logger.Error("sandbox execution operation failed", "operation", operation, "error", err)
		c.JSON(http.StatusInternalServerError, jsonObject{"error": operation + "_failed", "message": err.Error()})
	}
}
