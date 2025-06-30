package api

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/agentarea/mcp-manager/internal/container"
	"github.com/agentarea/mcp-manager/internal/models"
)

// Handler holds the HTTP handlers and dependencies
type Handler struct {
	containerManager *container.Manager
	startTime        time.Time
	version          string
}

// NewHandler creates a new API handler
func NewHandler(containerManager *container.Manager, version string) *Handler {
	return &Handler{
		containerManager: containerManager,
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

	// Container monitoring
	router.GET("/containers/:service/health", h.checkContainerHealth)
	router.POST("/containers/:service/health", h.healthCheckContainer)
	router.GET("/monitoring/status", h.getMonitoringStatus)
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

	// Create container (Traefik routing is handled automatically via labels)
	container, err := h.containerManager.CreateContainer(c.Request.Context(), req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, models.ErrorResponse{
			Error:   "container_creation_failed",
			Code:    http.StatusInternalServerError,
			Message: err.Error(),
		})
		return
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

	// Delete container (Traefik routes are automatically removed when container stops)
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

// checkContainerHealth checks if a specific container is healthy
func (h *Handler) checkContainerHealth(c *gin.Context) {
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

	// Get real-time container status
	status, err := h.containerManager.GetContainerStatus(c.Request.Context(), container.ServiceName)
	if err != nil {
		c.JSON(http.StatusInternalServerError, models.ErrorResponse{
			Error:   "status_check_failed",
			Code:    http.StatusInternalServerError,
			Message: err.Error(),
		})
		return
	}

	isHealthy := status == models.StatusRunning
	healthStatus := "unhealthy"
	if isHealthy {
		healthStatus = "healthy"
	}

	response := gin.H{
		"service":   serviceName,
		"status":    string(status),
		"healthy":   isHealthy,
		"health":    healthStatus,
		"timestamp": time.Now(),
		"container": container,
	}

	if isHealthy {
		c.JSON(http.StatusOK, response)
	} else {
		c.JSON(http.StatusServiceUnavailable, response)
	}
}

// healthCheckContainer performs an HTTP health check on the container's endpoint
func (h *Handler) healthCheckContainer(c *gin.Context) {
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

	// Perform HTTP health check
	healthStatus, err := h.containerManager.PerformHealthCheck(c.Request.Context(), container.ServiceName)
	if err != nil {
		c.JSON(http.StatusInternalServerError, models.ErrorResponse{
			Error:   "health_check_failed",
			Code:    http.StatusInternalServerError,
			Message: err.Error(),
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"service":       serviceName,
		"health_status": healthStatus,
		"timestamp":     time.Now(),
	})
}

// getMonitoringStatus returns the overall monitoring status
func (h *Handler) getMonitoringStatus(c *gin.Context) {
	containers := h.containerManager.ListContainers()

	totalContainers := len(containers)
	healthyContainers := 0
	unhealthyContainers := 0
	stoppedContainers := 0

	for _, container := range containers {
		switch container.Status {
		case models.StatusRunning:
			healthyContainers++
		case models.StatusStopped, models.StatusError:
			unhealthyContainers++
		default:
			stoppedContainers++
		}
	}

	response := gin.H{
		"total_containers":     totalContainers,
		"healthy_containers":   healthyContainers,
		"unhealthy_containers": unhealthyContainers,
		"stopped_containers":   stoppedContainers,
		"timestamp":            time.Now(),
		"uptime":               time.Since(h.startTime).String(),
	}

	c.JSON(http.StatusOK, response)
}
