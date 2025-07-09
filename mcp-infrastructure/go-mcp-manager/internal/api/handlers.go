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

	// Container validation
	router.POST("/containers/validate", h.validateContainer)

	// Container monitoring and health checks
	router.GET("/containers/:service/health", h.checkContainerHealth)
	router.POST("/containers/:service/health", h.healthCheckContainer)
	router.GET("/containers/:service/health/detailed", h.getDetailedContainerHealth)
	router.GET("/containers/health", h.healthCheckContainers) // New route for checking all containers
	router.GET("/monitoring/status", h.getMonitoringStatus)
	router.GET("/monitoring/health-summary", h.getHealthSummary)
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

// validateContainer validates a container configuration without creating it
func (h *Handler) validateContainer(c *gin.Context) {
	var req struct {
		InstanceID string                 `json:"instance_id"`
		Name       string                 `json:"name"`
		JSONSpec   map[string]interface{} `json:"json_spec"`
		DryRun     bool                   `json:"dry_run"`
	}

	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, models.ErrorResponse{
			Error:   "invalid_request",
			Code:    http.StatusBadRequest,
			Message: err.Error(),
		})
		return
	}

	// Create a temporary MCP server instance for validation
	instance := &models.MCPServerInstance{
		InstanceID: req.InstanceID,
		Name:       req.Name,
		JSONSpec:   req.JSONSpec,
		Status:     "validating",
	}

	// Perform validation with the container manager
	// Get current running count for validation
	currentRunningCount := h.containerManager.GetRunningCount()
	maxContainers := 10 // Default max containers - should be configurable

	result, err := h.containerManager.ValidateContainerSpecWithLimits(
		c.Request.Context(),
		instance,
		true, // allowImagePull
		currentRunningCount,
		maxContainers,
	)

	if err != nil {
		c.JSON(http.StatusInternalServerError, models.ErrorResponse{
			Error:   "validation_failed",
			Code:    http.StatusInternalServerError,
			Message: err.Error(),
		})
		return
	}

	// Return validation result
	c.JSON(http.StatusOK, gin.H{
		"valid":          result.Valid,
		"errors":         result.Errors,
		"warnings":       result.Warnings,
		"image_exists":   result.ImageExists,
		"can_pull":       result.CanPull,
		"estimated_size": result.EstimatedSize,
		"timestamp":      time.Now(),
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

// healthCheckContainers performs health checks on containers
func (h *Handler) healthCheckContainers(c *gin.Context) {
	serviceName := c.Query("service")

	if serviceName != "" {
		// Health check for specific container
		_, err := h.containerManager.GetContainer(serviceName)
		if err != nil {
			c.JSON(http.StatusNotFound, models.ErrorResponse{
				Error:   "container_not_found",
				Code:    http.StatusNotFound,
				Message: err.Error(),
			})
			return
		}

		// Perform health check
		healthResult, err := h.containerManager.PerformHealthCheck(c.Request.Context(), serviceName)
		if err != nil {
			c.JSON(http.StatusInternalServerError, models.ErrorResponse{
				Error:   "health_check_failed",
				Code:    http.StatusInternalServerError,
				Message: err.Error(),
			})
			return
		}

		c.JSON(http.StatusOK, healthResult)
	} else {
		// Health check for all containers
		containers := h.containerManager.ListContainers()
		healthResults := make([]map[string]interface{}, 0, len(containers))

		for _, container := range containers {
			healthResult, err := h.containerManager.PerformHealthCheck(c.Request.Context(), container.ServiceName)
			if err != nil {
				// Create error result for this container
				healthResult = map[string]interface{}{
					"service_name":     container.ServiceName,
					"container_status": string(container.Status),
					"healthy":          false,
					"error":            err.Error(),
					"timestamp":        time.Now(),
				}
			}
			healthResults = append(healthResults, healthResult)
		}

		c.JSON(http.StatusOK, map[string]interface{}{
			"health_checks": healthResults,
			"total":         len(healthResults),
		})
	}
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

// getDetailedContainerHealth performs detailed health check on a container
func (h *Handler) getDetailedContainerHealth(c *gin.Context) {
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

	// This is a placeholder - in real implementation, you'd use the health checker
	// healthResult, err := h.containerManager.healthChecker.PerformHealthCheck(c.Request.Context(), container)
	// For now, return basic health info
	response := gin.H{
		"container_id":   container.ID,
		"service_name":   container.ServiceName,
		"status":         string(container.Status),
		"healthy":        container.Status == models.StatusRunning,
		"http_reachable": false, // Would be determined by actual health check
		"response_time":  0,
		"timestamp":      time.Now(),
		"details": gin.H{
			"container_port": container.Port,
			"container_url":  container.URL,
			"created_at":     container.CreatedAt,
			"updated_at":     container.UpdatedAt,
		},
	}

	c.JSON(http.StatusOK, response)
}

// getHealthSummary returns a comprehensive health summary for all containers
func (h *Handler) getHealthSummary(c *gin.Context) {
	containers := h.containerManager.ListContainers()

	// This is a placeholder - in real implementation, you'd use the health checker
	// summary, err := h.containerManager.healthChecker.GetHealthSummary(c.Request.Context(), containerPtrs)
	// For now, return basic summary
	totalContainers := len(containers)
	runningCount := 0
	stoppedCount := 0
	errorCount := 0

	for _, container := range containers {
		switch container.Status {
		case models.StatusRunning:
			runningCount++
		case models.StatusStopped:
			stoppedCount++
		case models.StatusError:
			errorCount++
		}
	}

	response := gin.H{
		"total_containers":     totalContainers,
		"healthy_containers":   runningCount, // Simplified: consider running = healthy
		"unhealthy_containers": totalContainers - runningCount,
		"running_containers":   runningCount,
		"stopped_containers":   stoppedCount,
		"error_containers":     errorCount,
		"timestamp":            time.Now(),
		"uptime":               time.Since(h.startTime).String(),
	}

	c.JSON(http.StatusOK, response)
}
