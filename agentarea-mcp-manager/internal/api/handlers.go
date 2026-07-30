package api

import (
	"context"
	"log/slog"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/container"
	"github.com/agentarea/mcp-manager/internal/features"
	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/sandboxcontrol"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime"
)

// Handler holds the HTTP handlers and dependencies
type Handler struct {
	backend          backends.Backend
	containerManager *container.Manager // Keep for backward compatibility
	sandboxControl   *sandboxcontrol.Service
	sandboxRuntime   sandboxruntime.Runtime
	logger           *slog.Logger
	startTime        time.Time
	version          string
}

// NewHandler creates a new API handler
func NewHandler(backend backends.Backend, containerManager *container.Manager, logger *slog.Logger, version string, runtimes ...sandboxruntime.Runtime) *Handler {
	sandboxControl := newSandboxControlService(logger)
	var sandboxRuntime sandboxruntime.Runtime
	if len(runtimes) > 0 {
		sandboxRuntime = runtimes[0]
	}
	return &Handler{
		backend:          backend,
		containerManager: containerManager,
		sandboxControl:   sandboxControl,
		sandboxRuntime:   sandboxRuntime,
		logger:           logger,
		startTime:        time.Now(),
		version:          version,
	}
}

// SetupRoutes sets up the HTTP routes
func (h *Handler) SetupRoutes(router *gin.Engine) {
	// OpenAPI documentation routes
	h.SetupOpenAPIRoutes(router)

	// Health check
	router.GET("/health", h.healthCheck)
	router.GET("/runtime/manifest", h.runtimeManifest)

	// Instance management (backend-agnostic)
	router.GET("/instances", h.listInstances)
	router.POST("/instances", h.createInstance)
	router.GET("/instances/:id", h.getInstance)
	router.PUT("/instances/:id", h.updateInstance)
	router.DELETE("/instances/:id", h.deleteInstance)

	// Instance validation
	router.POST("/instances/validate", h.validateInstance)

	// Instance monitoring and health checks
	router.GET("/instances/:id/health", h.checkInstanceHealth)
	router.POST("/instances/:id/health", h.healthCheckInstance)
	router.GET("/instances/:id/health/detailed", h.getDetailedInstanceHealth)
	router.GET("/instances/health", h.healthCheckInstances)
	router.GET("/monitoring/status", h.getMonitoringStatus)
	router.GET("/monitoring/health-summary", h.getHealthSummary)

	// Sandbox execution (uses the sandbox control plane / warm-pool data plane)
	router.GET("/sandbox/sessions", h.listSandboxes)
	router.POST("/sandbox/executions", h.createSandboxExecution)
	router.GET("/sandbox/executions/:id", h.getSandboxExecution)
	router.POST("/sandbox/executions/:id/events", h.applySandboxExecutionEvent)
	// Sandbox file API: the file tool writes to the same filesystem bash uses.
	router.PUT("/sandbox/files", h.sandboxFiles)
	router.GET("/sandbox/files", h.sandboxFiles)
	// Per-task sandbox teardown, invoked by the Temporal workflow finalizer.
	router.DELETE("/sandbox/task/:id", h.deleteSandboxTask)

	// Container endpoints — only the Docker backend supplies a container manager.
	if h.containerManager != nil {
		router.GET("/containers", h.listContainers)
		router.POST("/containers", h.createContainer)
		router.GET("/containers/:service", h.getContainer)
		router.DELETE("/containers/:service", h.deleteContainer)
		router.POST("/containers/validate", h.validateContainer)
		router.GET("/containers/:service/health", h.checkContainerHealth)
		router.POST("/containers/:service/health", h.healthCheckContainer)
		router.GET("/containers/:service/health/detailed", h.getDetailedContainerHealth)
		router.GET("/containers/health", h.healthCheckContainers)
	}
}

type runtimeManifestProvider interface {
	RuntimeManifest(context.Context, string) (*runtimeinfo.Manifest, error)
}

func (h *Handler) runtimeManifest(c *gin.Context) {
	packageInstall := c.DefaultQuery("package_install", runtimeinfo.PackageInstallAllowed)
	if err := runtimeinfo.ValidatePackageInstall(packageInstall); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error":   "invalid_package_install",
			"message": err.Error(),
		})
		return
	}
	var provider runtimeManifestProvider
	if h.sandboxRuntime != nil {
		provider = h.sandboxRuntime
	} else {
		provider, _ = h.backend.(runtimeManifestProvider)
	}
	ok := provider != nil
	if !ok {
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"error":   "runtime_manifest_unavailable",
			"message": "sandbox backend does not expose a runtime manifest",
		})
		return
	}
	manifest, err := provider.RuntimeManifest(c.Request.Context(), packageInstall)
	if err != nil {
		h.logger.Warn("Runtime manifest discovery failed", slog.String("error", err.Error()))
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"error":   "runtime_manifest_unavailable",
			"message": err.Error(),
		})
		return
	}
	c.JSON(http.StatusOK, manifest)
}

// healthCheck returns the health status of the service
func (h *Handler) healthCheck(c *gin.Context) {
	// Get instance count from backend
	instancesRunning := 0
	if instances, err := h.backend.ListInstances(c.Request.Context()); err == nil {
		for _, instance := range instances {
			if instance.Status == "running" {
				instancesRunning++
			}
		}
	}

	uptime := time.Since(h.startTime).String()

	response := models.HealthResponse{
		Status:            "healthy",
		Version:           h.version,
		ContainersRunning: instancesRunning, // Keep field name for backward compatibility
		Timestamp:         time.Now(),
		Uptime:            uptime,
	}

	c.JSON(http.StatusOK, response)
}

// Backend-agnostic instance management methods

// listInstances returns a list of all managed instances
func (h *Handler) listInstances(c *gin.Context) {
	instances, err := h.backend.ListInstances(c.Request.Context())
	if err != nil {
		h.logger.Error("Failed to list instances", slog.String("error", err.Error()))
		c.JSON(http.StatusInternalServerError, models.ErrorResponse{
			Error:   "list_instances_failed",
			Code:    http.StatusInternalServerError,
			Message: err.Error(),
		})
		return
	}

	response := gin.H{
		"instances": instances,
		"total":     len(instances),
	}

	c.JSON(http.StatusOK, response)
}

// createInstance creates a new MCP server instance
func (h *Handler) createInstance(c *gin.Context) {
	var req struct {
		InstanceID  string                 `json:"instance_id" binding:"required"`
		Name        string                 `json:"name" binding:"required"`
		ServiceName string                 `json:"service_name" binding:"required"`
		Image       string                 `json:"image"` // optional when json_spec is provided
		Port        int                    `json:"port"`
		Command     []string               `json:"command,omitempty"`
		Environment map[string]string      `json:"environment,omitempty"`
		WorkspaceID string                 `json:"workspace_id" binding:"required"`
		JSONSpec    map[string]interface{} `json:"json_spec,omitempty"` // full spec; takes precedence when present
		Resources   struct {
			Requests backends.ResourceList `json:"requests,omitempty"`
			Limits   backends.ResourceList `json:"limits,omitempty"`
		} `json:"resources,omitempty"`
	}

	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, models.ErrorResponse{
			Error:   "invalid_request",
			Code:    http.StatusBadRequest,
			Message: err.Error(),
		})
		return
	}

	// If a full json_spec is supplied, resolve the effective image/port/command from it.
	// This handles both "docker" type (image+port) and "command" type (sandbox+mcp-bridge).
	if len(req.JSONSpec) > 0 {
		image, port, command, environment := container.ResolveContainerSpec(req.JSONSpec)
		if req.Image == "" {
			req.Image = image
		}
		if req.Port == 0 {
			req.Port = port
		}
		if len(req.Command) == 0 {
			req.Command = command
		}
		// Merge environment: json_spec env vars are the base; request-level env overrides
		if req.Environment == nil {
			req.Environment = make(map[string]string)
		}
		for k, v := range environment {
			if _, exists := req.Environment[k]; !exists {
				req.Environment[k] = v
			}
		}

		// Resolve secret env vars (json_spec.env_vars -> encrypted_secrets) and
		// merge them in. This HTTP path owns provisioning, so secrets must be
		// injected here — they are stripped out of json_spec.environment at create
		// time and only their names travel in the spec. Request-level env wins.
		for k, v := range h.containerManager.ResolveSecretEnvVars(req.InstanceID, req.JSONSpec) {
			if _, exists := req.Environment[k]; !exists {
				req.Environment[k] = v
			}
		}
	}

	if req.Image == "" {
		c.JSON(http.StatusBadRequest, models.ErrorResponse{
			Error:   "invalid_request",
			Code:    http.StatusBadRequest,
			Message: "image is required (provide image directly or via json_spec with type='docker'/'command')",
		})
		return
	}

	// Set default port if not specified
	if req.Port == 0 {
		req.Port = 8000
	}

	// Use instance_id as service_name for deterministic routing
	serviceName := req.InstanceID

	// Create instance spec
	spec := &backends.InstanceSpec{
		InstanceID:  req.InstanceID,
		Name:        req.Name,
		ServiceName: serviceName,
		Image:       req.Image,
		Port:        req.Port,
		Command:     req.Command,
		Environment: req.Environment,
		WorkspaceID: req.WorkspaceID,
		Resources: backends.ResourceRequirements{
			Requests: req.Resources.Requests,
			Limits:   req.Resources.Limits,
		},
	}

	var result *backends.InstanceResult
	var err error

	// Try warm pool if enabled and backend supports it
	if features.IsEnabled(features.WarmPool) {
		if k8sBackend, ok := h.backend.(*backends.KubernetesBackend); ok {
			h.logger.Info("Attempting to create instance with warm pool",
				slog.String("instance_id", req.InstanceID))
			result, err = k8sBackend.CreateInstanceWithWarmPool(c.Request.Context(), spec)
		} else {
			result, err = h.backend.CreateInstance(c.Request.Context(), spec)
		}
	} else {
		result, err = h.backend.CreateInstance(c.Request.Context(), spec)
	}
	if err != nil {
		h.logger.Error("Failed to create instance", slog.String("error", err.Error()))
		c.JSON(http.StatusInternalServerError, models.ErrorResponse{
			Error:   "instance_creation_failed",
			Code:    http.StatusInternalServerError,
			Message: err.Error(),
		})
		return
	}

	c.JSON(http.StatusCreated, result)
}

// getInstance returns details of a specific instance
func (h *Handler) getInstance(c *gin.Context) {
	instanceID := c.Param("id")

	instance, err := h.backend.GetInstanceStatus(c.Request.Context(), instanceID)
	if err != nil {
		h.logger.Error("Failed to get instance", slog.String("instance_id", instanceID), slog.String("error", err.Error()))
		c.JSON(http.StatusNotFound, models.ErrorResponse{
			Error:   "instance_not_found",
			Code:    http.StatusNotFound,
			Message: err.Error(),
		})
		return
	}

	c.JSON(http.StatusOK, instance)
}

// updateInstance updates an existing instance
func (h *Handler) updateInstance(c *gin.Context) {
	instanceID := c.Param("id")

	var req struct {
		Image       string            `json:"image,omitempty"`
		Port        int               `json:"port,omitempty"`
		Command     []string          `json:"command,omitempty"`
		Environment map[string]string `json:"environment,omitempty"`
		Resources   struct {
			Requests backends.ResourceList `json:"requests,omitempty"`
			Limits   backends.ResourceList `json:"limits,omitempty"`
		} `json:"resources,omitempty"`
	}

	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, models.ErrorResponse{
			Error:   "invalid_request",
			Code:    http.StatusBadRequest,
			Message: err.Error(),
		})
		return
	}

	// Get current instance to fill in missing fields
	currentInstance, err := h.backend.GetInstanceStatus(c.Request.Context(), instanceID)
	if err != nil {
		c.JSON(http.StatusNotFound, models.ErrorResponse{
			Error:   "instance_not_found",
			Code:    http.StatusNotFound,
			Message: err.Error(),
		})
		return
	}

	// Create update spec with current values as defaults
	spec := &backends.InstanceSpec{
		InstanceID:  currentInstance.ID,
		Name:        currentInstance.Name,
		ServiceName: currentInstance.ServiceName,
		Image:       currentInstance.Image,
		Port:        currentInstance.Port,
		Environment: currentInstance.Environment,
		WorkspaceID: "", // This should come from the current instance context
	}

	// Apply updates
	if req.Image != "" {
		spec.Image = req.Image
	}
	if req.Port != 0 {
		spec.Port = req.Port
	}
	if req.Command != nil {
		spec.Command = req.Command
	}
	if req.Environment != nil {
		spec.Environment = req.Environment
	}

	// Update resources
	spec.Resources = backends.ResourceRequirements{
		Requests: req.Resources.Requests,
		Limits:   req.Resources.Limits,
	}

	err = h.backend.UpdateInstance(c.Request.Context(), instanceID, spec)
	if err != nil {
		h.logger.Error("Failed to update instance", slog.String("instance_id", instanceID), slog.String("error", err.Error()))
		c.JSON(http.StatusInternalServerError, models.ErrorResponse{
			Error:   "instance_update_failed",
			Code:    http.StatusInternalServerError,
			Message: err.Error(),
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"message":     "Instance updated successfully",
		"instance_id": instanceID,
	})
}

// deleteInstance removes an instance
func (h *Handler) deleteInstance(c *gin.Context) {
	instanceID := c.Param("id")

	err := h.backend.DeleteInstance(c.Request.Context(), instanceID)
	if err != nil {
		h.logger.Error("Failed to delete instance", slog.String("instance_id", instanceID), slog.String("error", err.Error()))
		c.JSON(http.StatusInternalServerError, models.ErrorResponse{
			Error:   "instance_deletion_failed",
			Code:    http.StatusInternalServerError,
			Message: err.Error(),
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"message":     "Instance deleted successfully",
		"instance_id": instanceID,
	})
}

// validateInstance validates an instance configuration without creating it
func (h *Handler) validateInstance(c *gin.Context) {
	var req struct {
		InstanceID  string            `json:"instance_id" binding:"required"`
		Name        string            `json:"name" binding:"required"`
		ServiceName string            `json:"service_name" binding:"required"`
		Image       string            `json:"image" binding:"required"`
		Port        int               `json:"port"`
		Command     []string          `json:"command,omitempty"`
		Environment map[string]string `json:"environment,omitempty"`
		WorkspaceID string            `json:"workspace_id" binding:"required"`
		DryRun      bool              `json:"dry_run"`
	}

	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, models.ErrorResponse{
			Error:   "invalid_request",
			Code:    http.StatusBadRequest,
			Message: err.Error(),
		})
		return
	}

	// For now, perform basic validation
	// In a full implementation, this would validate the spec against the backend
	errors := []string{}
	warnings := []string{}

	if req.Port == 0 {
		req.Port = 8000
		warnings = append(warnings, "Port not specified, using default port 8000")
	}

	if req.Port < 1 || req.Port > 65535 {
		errors = append(errors, "Port must be between 1 and 65535")
	}

	// Basic image validation
	if req.Image == "" {
		errors = append(errors, "Image is required")
	}

	valid := len(errors) == 0

	c.JSON(http.StatusOK, gin.H{
		"valid":          valid,
		"errors":         errors,
		"warnings":       warnings,
		"image_exists":   true, // Would need to check this against the backend
		"can_pull":       true, // Would need to check this against the backend
		"estimated_size": "unknown",
		"timestamp":      time.Now(),
	})
}

// checkInstanceHealth checks if a specific instance is healthy
func (h *Handler) checkInstanceHealth(c *gin.Context) {
	instanceID := c.Param("id")

	healthResult, err := h.backend.PerformHealthCheck(c.Request.Context(), instanceID)
	if err != nil {
		h.logger.Error("Failed to perform health check", slog.String("instance_id", instanceID), slog.String("error", err.Error()))
		c.JSON(http.StatusInternalServerError, models.ErrorResponse{
			Error:   "health_check_failed",
			Code:    http.StatusInternalServerError,
			Message: err.Error(),
		})
		return
	}

	statusCode := http.StatusOK
	if !healthResult.Healthy {
		statusCode = http.StatusServiceUnavailable
	}

	c.JSON(statusCode, healthResult)
}

// healthCheckInstance performs an HTTP health check on the instance's endpoint
func (h *Handler) healthCheckInstance(c *gin.Context) {
	instanceID := c.Param("id")

	healthResult, err := h.backend.PerformHealthCheck(c.Request.Context(), instanceID)
	if err != nil {
		h.logger.Error("Failed to perform health check", slog.String("instance_id", instanceID), slog.String("error", err.Error()))
		c.JSON(http.StatusInternalServerError, models.ErrorResponse{
			Error:   "health_check_failed",
			Code:    http.StatusInternalServerError,
			Message: err.Error(),
		})
		return
	}

	c.JSON(http.StatusOK, healthResult)
}

// getDetailedInstanceHealth performs detailed health check on an instance
func (h *Handler) getDetailedInstanceHealth(c *gin.Context) {
	instanceID := c.Param("id")

	// Get instance status first
	instance, err := h.backend.GetInstanceStatus(c.Request.Context(), instanceID)
	if err != nil {
		c.JSON(http.StatusNotFound, models.ErrorResponse{
			Error:   "instance_not_found",
			Code:    http.StatusNotFound,
			Message: err.Error(),
		})
		return
	}

	// Perform health check
	healthResult, err := h.backend.PerformHealthCheck(c.Request.Context(), instanceID)
	if err != nil {
		h.logger.Error("Failed to perform health check", slog.String("instance_id", instanceID), slog.String("error", err.Error()))
		healthResult = &backends.HealthCheckResult{
			Healthy:     false,
			Status:      "error",
			ServiceName: instance.ServiceName,
			Error:       err.Error(),
			Timestamp:   time.Now(),
		}
	}

	response := gin.H{
		"instance_id":    instance.ID,
		"service_name":   instance.ServiceName,
		"status":         instance.Status,
		"healthy":        healthResult.Healthy,
		"http_reachable": healthResult.HTTPReachable,
		"response_time":  healthResult.ResponseTime,
		"timestamp":      healthResult.Timestamp,
		"details": gin.H{
			"instance_port": instance.Port,
			"instance_url":  instance.URL,
			"created_at":    instance.CreatedAt,
			"updated_at":    instance.UpdatedAt,
		},
	}

	c.JSON(http.StatusOK, response)
}

// healthCheckInstances performs health checks on instances
func (h *Handler) healthCheckInstances(c *gin.Context) {
	instanceID := c.Query("instance_id")

	if instanceID != "" {
		// Health check for specific instance
		healthResult, err := h.backend.PerformHealthCheck(c.Request.Context(), instanceID)
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
		// Health check for all instances
		instances, err := h.backend.ListInstances(c.Request.Context())
		if err != nil {
			c.JSON(http.StatusInternalServerError, models.ErrorResponse{
				Error:   "list_instances_failed",
				Code:    http.StatusInternalServerError,
				Message: err.Error(),
			})
			return
		}

		healthResults := make([]interface{}, 0, len(instances))
		for _, instance := range instances {
			healthResult, err := h.backend.PerformHealthCheck(c.Request.Context(), instance.ID)
			if err != nil {
				// Create error result for this instance
				healthResult = &backends.HealthCheckResult{
					Healthy:     false,
					Status:      "error",
					ServiceName: instance.ServiceName,
					Error:       err.Error(),
					Timestamp:   time.Now(),
				}
			}
			healthResults = append(healthResults, healthResult)
		}

		c.JSON(http.StatusOK, gin.H{
			"health_checks": healthResults,
			"total":         len(healthResults),
		})
	}
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
	// Use backend to get instance status
	instances, err := h.backend.ListInstances(c.Request.Context())
	if err != nil {
		h.logger.Error("Failed to list instances for monitoring", slog.String("error", err.Error()))
		c.JSON(http.StatusInternalServerError, models.ErrorResponse{
			Error:   "monitoring_status_failed",
			Code:    http.StatusInternalServerError,
			Message: err.Error(),
		})
		return
	}

	totalInstances := len(instances)
	healthyInstances := 0
	unhealthyInstances := 0
	stoppedInstances := 0

	for _, instance := range instances {
		switch instance.Status {
		case "running":
			healthyInstances++
		case "stopped", "error":
			unhealthyInstances++
		default:
			stoppedInstances++
		}
	}

	response := gin.H{
		"total_containers":     totalInstances,     // Keep field name for backward compatibility
		"healthy_containers":   healthyInstances,   // Keep field name for backward compatibility
		"unhealthy_containers": unhealthyInstances, // Keep field name for backward compatibility
		"stopped_containers":   stoppedInstances,   // Keep field name for backward compatibility
		"total_instances":      totalInstances,
		"healthy_instances":    healthyInstances,
		"unhealthy_instances":  unhealthyInstances,
		"stopped_instances":    stoppedInstances,
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

// getHealthSummary returns a comprehensive health summary for all instances
func (h *Handler) getHealthSummary(c *gin.Context) {
	// Use backend to get instance status
	instances, err := h.backend.ListInstances(c.Request.Context())
	if err != nil {
		h.logger.Error("Failed to list instances for health summary", slog.String("error", err.Error()))
		c.JSON(http.StatusInternalServerError, models.ErrorResponse{
			Error:   "health_summary_failed",
			Code:    http.StatusInternalServerError,
			Message: err.Error(),
		})
		return
	}

	totalInstances := len(instances)
	runningCount := 0
	stoppedCount := 0
	errorCount := 0

	for _, instance := range instances {
		switch instance.Status {
		case "running":
			runningCount++
		case "stopped":
			stoppedCount++
		case "error":
			errorCount++
		}
	}

	response := gin.H{
		"total_containers":     totalInstances,                // Keep field name for backward compatibility
		"healthy_containers":   runningCount,                  // Simplified: consider running = healthy
		"unhealthy_containers": totalInstances - runningCount, // Keep field name for backward compatibility
		"running_containers":   runningCount,                  // Keep field name for backward compatibility
		"stopped_containers":   stoppedCount,                  // Keep field name for backward compatibility
		"error_containers":     errorCount,                    // Keep field name for backward compatibility
		"total_instances":      totalInstances,
		"healthy_instances":    runningCount,
		"unhealthy_instances":  totalInstances - runningCount,
		"running_instances":    runningCount,
		"stopped_instances":    stoppedCount,
		"error_instances":      errorCount,
		"timestamp":            time.Now(),
		"uptime":               time.Since(h.startTime).String(),
	}

	c.JSON(http.StatusOK, response)
}
