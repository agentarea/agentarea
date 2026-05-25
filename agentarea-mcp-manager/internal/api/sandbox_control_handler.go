package api

import (
	"errors"
	"log/slog"
	"net/http"
	"os"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/agentarea/mcp-manager/internal/sandboxcontrol"
)

func newSandboxControlService(logger *slog.Logger) *sandboxcontrol.Service {
	store, err := sandboxcontrol.NewRedisStore(
		os.Getenv("REDIS_URL"),
		os.Getenv("SANDBOX_CONTROL_REDIS_PREFIX"),
		getAPIDurationEnv("SANDBOX_EXECUTION_RECORD_TTL", 24*time.Hour),
	)
	if err != nil {
		logger.Warn("sandbox control store unavailable", "error", err)
		return nil
	}
	eventBus := sandboxcontrol.NewRedisEventBus(
		store.RedisClient(),
		os.Getenv("SANDBOX_EXECUTION_REQUEST_STREAM"),
		os.Getenv("SANDBOX_EXECUTION_EVENT_STREAM"),
		"agentarea.mcp-manager.sandbox-control",
	)
	return sandboxcontrol.NewService(store, eventBus)
}

func getAPIDurationEnv(name string, fallback time.Duration) time.Duration {
	value := os.Getenv(name)
	if value == "" {
		return fallback
	}
	duration, err := time.ParseDuration(value)
	if err != nil {
		return fallback
	}
	return duration
}

func (h *Handler) createSandboxExecution(c *gin.Context) {
	if h.sandboxControl == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"error":   "sandbox_control_unavailable",
			"message": "sandbox control plane is not configured",
		})
		return
	}

	var req sandboxcontrol.ExecutionCreateRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_request", "message": err.Error()})
		return
	}
	record, err := h.sandboxControl.CreateExecution(c.Request.Context(), req)
	if err != nil {
		h.logger.Error("sandbox execution create failed", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "create_failed", "message": err.Error()})
		return
	}
	c.JSON(http.StatusAccepted, record)
}

func (h *Handler) getSandboxExecution(c *gin.Context) {
	if h.sandboxControl == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"error":   "sandbox_control_unavailable",
			"message": "sandbox control plane is not configured",
		})
		return
	}
	record, err := h.sandboxControl.GetExecution(c.Request.Context(), c.Param("id"))
	if err != nil {
		if errors.Is(err, sandboxcontrol.ErrExecutionNotFound) {
			c.JSON(http.StatusNotFound, gin.H{"error": "not_found"})
			return
		}
		h.logger.Error("sandbox execution get failed", "execution_id", c.Param("id"), "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "get_failed", "message": err.Error()})
		return
	}
	c.JSON(http.StatusOK, record)
}

func (h *Handler) applySandboxExecutionEvent(c *gin.Context) {
	if h.sandboxControl == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"error":   "sandbox_control_unavailable",
			"message": "sandbox control plane is not configured",
		})
		return
	}

	var req sandboxcontrol.ExecutionEventRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_request", "message": err.Error()})
		return
	}
	record, err := h.sandboxControl.ApplyExecutionEvent(c.Request.Context(), c.Param("id"), req)
	if err != nil {
		if errors.Is(err, sandboxcontrol.ErrExecutionNotFound) {
			c.JSON(http.StatusNotFound, gin.H{"error": "not_found"})
			return
		}
		h.logger.Error("sandbox execution event apply failed", "execution_id", c.Param("id"), "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "event_failed", "message": err.Error()})
		return
	}
	c.JSON(http.StatusOK, record)
}
