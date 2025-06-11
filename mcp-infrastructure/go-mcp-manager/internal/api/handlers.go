package api

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/agentarea/mcp-manager/internal/caddy"
	"github.com/agentarea/mcp-manager/internal/container"
	"github.com/agentarea/mcp-manager/internal/models"
)

// Handler holds the HTTP handlers and dependencies
type Handler struct {
	containerManager *container.Manager
	caddyClient      *caddy.Client
	startTime        time.Time
	version          string
}

// NewHandler creates a new API handler
func NewHandler(containerManager *container.Manager, caddyClient *caddy.Client, version string) *Handler {
	return &Handler{
		containerManager: containerManager,
		caddyClient:      caddyClient,
		startTime:        time.Now(),
		version:          version,
	}
}

// SetupRoutes sets up the HTTP routes
func (h *Handler) SetupRoutes(router *gin.Engine) {
	// Health check
	router.GET("/health", h.healthCheck)

	// Container management
	router.GET("/containers", h.listContainers)
	router.POST("/containers", h.createContainer)
	router.GET("/containers/:service", h.getContainer)
	router.DELETE("/containers/:service", h.deleteContainer)

	// Template management
	router.GET("/templates", h.listTemplates)

	// Caddy management
	router.GET("/caddy/status", h.getCaddyStatus)
}

// healthCheck returns the health status of the service
func (h *Handler) healthCheck(c *gin.Context) {
	containersRunning := h.containerManager.GetRunningCount()
	uptime := time.Since(h.startTime).String()

	response := models.HealthResponse{
		Status:            "healthy",
		Version:           h.version,
		ContainersRunning: containersRunning,
		Timestamp:         time.Now(),
		Uptime:            uptime,
	}

	c.JSON(http.StatusOK, response)
}

// listContainers returns a list of all managed containers
func (h *Handler) listContainers(c *gin.Context) {
	containers := h.containerManager.ListContainers()

	response := models.ListContainersResponse{
		Containers: containers,
		Total:      len(containers),
	}

	c.JSON(http.StatusOK, response)
}

// createContainer creates a new container from a template
func (h *Handler) createContainer(c *gin.Context) {
	var req models.CreateContainerRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, models.ErrorResponse{
			Error:   "invalid_request",
			Code:    http.StatusBadRequest,
			Message: err.Error(),
		})
		return
	}

	// Create container
	container, err := h.containerManager.CreateContainer(c.Request.Context(), req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, models.ErrorResponse{
			Error:   "container_creation_failed",
			Code:    http.StatusInternalServerError,
			Message: err.Error(),
		})
		return
	}

	// Add route to Caddy
	if err := h.caddyClient.AddService(req.ServiceName, container.Port); err != nil {
		// Log error but don't fail the request
		// Container is created successfully, route addition is best effort
		c.Header("X-Warning", "Failed to add route to Caddy: "+err.Error())
	}

	c.JSON(http.StatusCreated, container)
}

// getContainer returns details of a specific container
func (h *Handler) getContainer(c *gin.Context) {
	serviceName := c.Param("service")

	container, err := h.containerManager.GetContainer(serviceName)
	if err != nil {
		c.JSON(http.StatusNotFound, models.ErrorResponse{
			Error:   "container_not_found",
			Code:    http.StatusNotFound,
			Message: err.Error(),
		})
		return
	}

	c.JSON(http.StatusOK, container)
}

// deleteContainer stops and removes a container
func (h *Handler) deleteContainer(c *gin.Context) {
	serviceName := c.Param("service")

	// Remove route from Caddy first
	if err := h.caddyClient.RemoveService(serviceName); err != nil {
		// Log error but continue with container deletion
		c.Header("X-Warning", "Failed to remove route from Caddy: "+err.Error())
	}

	// Delete container
	if err := h.containerManager.DeleteContainer(c.Request.Context(), serviceName); err != nil {
		c.JSON(http.StatusInternalServerError, models.ErrorResponse{
			Error:   "container_deletion_failed",
			Code:    http.StatusInternalServerError,
			Message: err.Error(),
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"message": "Container deleted successfully",
		"service": serviceName,
	})
}

// listTemplates returns a list of available templates
func (h *Handler) listTemplates(c *gin.Context) {
	templates := h.containerManager.ListTemplates()

	response := models.ListTemplatesResponse{
		Templates: templates,
		Total:     len(templates),
	}

	c.JSON(http.StatusOK, response)
}

// getCaddyStatus returns the status of Caddy
func (h *Handler) getCaddyStatus(c *gin.Context) {
	status := h.caddyClient.GetStatus()
	c.JSON(http.StatusOK, status)
}
