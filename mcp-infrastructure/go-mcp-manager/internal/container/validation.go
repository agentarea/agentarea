package container

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"os/exec"
	"strings"

	"github.com/agentarea/mcp-manager/internal/models"
)

// ValidationResult represents the result of container validation
type ValidationResult struct {
	Valid         bool     `json:"valid"`
	Errors        []string `json:"errors,omitempty"`
	Warnings      []string `json:"warnings,omitempty"`
	ImageExists   bool     `json:"image_exists"`
	CanPull       bool     `json:"can_pull"`
	EstimatedSize string   `json:"estimated_size,omitempty"`
}

// ContainerValidator handles container validation and dry-run checks
type ContainerValidator struct {
	logger  *slog.Logger
	manager *Manager
}

// NewContainerValidator creates a new container validator
func NewContainerValidator(logger *slog.Logger, manager *Manager) *ContainerValidator {
	return &ContainerValidator{
		logger:  logger,
		manager: manager,
	}
}

// ValidateContainerImage validates that a container image exists and can be used
func (v *ContainerValidator) ValidateContainerImage(ctx context.Context, imageName string, allowPull bool) (*ValidationResult, error) {
	v.logger.Info("Validating container image",
		slog.String("image", imageName),
		slog.Bool("allow_pull", allowPull))

	result := &ValidationResult{
		Valid:    true,
		Errors:   []string{},
		Warnings: []string{},
	}

	// Check if image exists locally
	exists, err := v.imageExistsLocally(ctx, imageName)
	if err != nil {
		result.Errors = append(result.Errors, fmt.Sprintf("Failed to check image existence: %v", err))
		result.Valid = false
		return result, nil
	}

	result.ImageExists = exists

	if !exists {
		v.logger.Info("Image not found locally, checking if it can be pulled",
			slog.String("image", imageName))

		if allowPull {
			canPull, err := v.canPullImage(ctx, imageName)
			if err != nil {
				result.Errors = append(result.Errors, fmt.Sprintf("Failed to check if image can be pulled: %v", err))
				result.Valid = false
				return result, nil
			}
			result.CanPull = canPull

			if !canPull {
				result.Errors = append(result.Errors, fmt.Sprintf("Image %s does not exist locally and cannot be pulled", imageName))
				result.Valid = false
			} else {
				result.Warnings = append(result.Warnings, fmt.Sprintf("Image %s will be pulled during container creation", imageName))
			}
		} else {
			result.Errors = append(result.Errors, fmt.Sprintf("Image %s does not exist locally and pulling is disabled", imageName))
			result.Valid = false
		}
	}

	// Get image info if it exists
	if exists {
		size, err := v.getImageSize(ctx, imageName)
		if err != nil {
			v.logger.Warn("Failed to get image size", slog.String("error", err.Error()))
		} else {
			result.EstimatedSize = size
		}
	}

	return result, nil
}

// imageExistsLocally checks if an image exists in the local registry
func (v *ContainerValidator) imageExistsLocally(ctx context.Context, imageName string) (bool, error) {
	cmd := exec.CommandContext(ctx, "podman", "image", "exists", imageName)
	err := cmd.Run()
	return err == nil, nil
}

// canPullImage checks if an image can be pulled from a registry
func (v *ContainerValidator) canPullImage(ctx context.Context, imageName string) (bool, error) {
	// Use podman search to check if image is available in registries
	cmd := exec.CommandContext(ctx, "podman", "search", "--limit", "1", imageName)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return false, nil // If search fails, assume image cannot be pulled
	}

	// Check if the output contains results
	outputStr := string(output)
	lines := strings.Split(outputStr, "\n")

	// Skip header line and check if there are any results
	for i, line := range lines {
		if i == 0 || strings.TrimSpace(line) == "" {
			continue
		}
		// If we have at least one result line, image can be pulled
		return true, nil
	}

	return false, nil
}

// getImageSize gets the size of a local image
func (v *ContainerValidator) getImageSize(ctx context.Context, imageName string) (string, error) {
	cmd := exec.CommandContext(ctx, "podman", "image", "inspect", imageName, "--format", "{{.Size}}")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return "", err
	}

	size := strings.TrimSpace(string(output))
	return v.formatSize(size), nil
}

// formatSize formats byte size into human-readable format
func (v *ContainerValidator) formatSize(sizeStr string) string {
	// This is a simplified version - in production you'd want better formatting
	return sizeStr + " bytes"
}

// DryRunValidation performs comprehensive dry-run validation
func (v *ContainerValidator) DryRunValidation(ctx context.Context, instance *models.MCPServerInstance) (*ValidationResult, error) {
	v.logger.Info("Performing dry-run validation",
		slog.String("instance_id", instance.InstanceID),
		slog.String("name", instance.Name))

	result := &ValidationResult{
		Valid:    true,
		Errors:   []string{},
		Warnings: []string{},
	}

	// Validate json_spec structure
	if err := v.validateJSONSpec(instance.JSONSpec); err != nil {
		result.Errors = append(result.Errors, fmt.Sprintf("Invalid JSON spec: %v", err))
		result.Valid = false
	}

	// Extract image from json_spec
	image, ok := instance.JSONSpec["image"].(string)
	if !ok || image == "" {
		result.Errors = append(result.Errors, "Missing or invalid image in json_spec")
		result.Valid = false
		return result, nil
	}

	// Validate container image
	imageValidation, err := v.ValidateContainerImage(ctx, image, true)
	if err != nil {
		result.Errors = append(result.Errors, fmt.Sprintf("Image validation failed: %v", err))
		result.Valid = false
		return result, nil
	}

	// Merge image validation results
	result.ImageExists = imageValidation.ImageExists
	result.CanPull = imageValidation.CanPull
	result.EstimatedSize = imageValidation.EstimatedSize
	result.Errors = append(result.Errors, imageValidation.Errors...)
	result.Warnings = append(result.Warnings, imageValidation.Warnings...)

	if !imageValidation.Valid {
		result.Valid = false
	}

	// Check container limits
	if v.manager != nil {
		runningCount := v.manager.GetRunningCount()
		maxContainers := v.manager.config.Container.MaxContainers

		if runningCount >= maxContainers {
			result.Errors = append(result.Errors, fmt.Sprintf("Container limit reached: %d/%d", runningCount, maxContainers))
			result.Valid = false
		} else if runningCount >= maxContainers-1 {
			result.Warnings = append(result.Warnings, fmt.Sprintf("Close to container limit: %d/%d", runningCount, maxContainers))
		}
	}

	// Validate resource requirements
	if err := v.validateResourceRequirements(instance.JSONSpec); err != nil {
		result.Warnings = append(result.Warnings, fmt.Sprintf("Resource validation: %v", err))
	}

	// Check for naming conflicts
	if v.manager != nil {
		containerName := v.manager.config.GetContainerName(instance.Name)
		if _, exists := v.manager.containers[containerName]; exists {
			result.Errors = append(result.Errors, fmt.Sprintf("Container with name %s already exists", containerName))
			result.Valid = false
		}
	}

	v.logger.Info("Dry-run validation completed",
		slog.String("instance_id", instance.InstanceID),
		slog.Bool("valid", result.Valid),
		slog.Int("errors", len(result.Errors)),
		slog.Int("warnings", len(result.Warnings)))

	return result, nil
}

// DryRunValidationWithLimits performs comprehensive dry-run validation with explicit limits (deadlock-safe)
func (v *ContainerValidator) DryRunValidationWithLimits(ctx context.Context, instance *models.MCPServerInstance, currentRunningCount int, maxContainers int) (*ValidationResult, error) {
	v.logger.Info("Performing dry-run validation with limits",
		slog.String("instance_id", instance.InstanceID),
		slog.String("name", instance.Name),
		slog.Int("current_running", currentRunningCount),
		slog.Int("max_containers", maxContainers))

	result := &ValidationResult{
		Valid:    true,
		Errors:   []string{},
		Warnings: []string{},
	}

	// Validate json_spec structure
	if err := v.validateJSONSpec(instance.JSONSpec); err != nil {
		result.Errors = append(result.Errors, fmt.Sprintf("Invalid JSON spec: %v", err))
		result.Valid = false
	}

	// Extract image from json_spec
	image, ok := instance.JSONSpec["image"].(string)
	if !ok || image == "" {
		result.Errors = append(result.Errors, "Missing or invalid image in json_spec")
		result.Valid = false
		return result, nil
	}

	// Validate container image
	imageValidation, err := v.ValidateContainerImage(ctx, image, true)
	if err != nil {
		result.Errors = append(result.Errors, fmt.Sprintf("Image validation failed: %v", err))
		result.Valid = false
		return result, nil
	}

	// Merge image validation results
	result.ImageExists = imageValidation.ImageExists
	result.CanPull = imageValidation.CanPull
	result.EstimatedSize = imageValidation.EstimatedSize
	result.Errors = append(result.Errors, imageValidation.Errors...)
	result.Warnings = append(result.Warnings, imageValidation.Warnings...)

	if !imageValidation.Valid {
		result.Valid = false
	}

	// Check container limits using provided values (no manager callbacks)
	if currentRunningCount >= maxContainers {
		result.Errors = append(result.Errors, fmt.Sprintf("Container limit reached: %d/%d", currentRunningCount, maxContainers))
		result.Valid = false
	} else if currentRunningCount >= maxContainers-1 {
		result.Warnings = append(result.Warnings, fmt.Sprintf("Close to container limit: %d/%d", currentRunningCount, maxContainers))
	}

	// Validate resource requirements
	if err := v.validateResourceRequirements(instance.JSONSpec); err != nil {
		result.Warnings = append(result.Warnings, fmt.Sprintf("Resource validation: %v", err))
	}

	// Check for naming conflicts (simplified - we'll check this in the manager after acquiring the lock)
	if v.manager != nil {
		containerName := v.manager.config.GetContainerName(instance.Name)
		// Note: We skip the container existence check here to avoid mutex deadlock
		// This will be checked in the manager after acquiring the lock
		v.logger.Debug("Skipping container name conflict check during validation to avoid deadlock",
			slog.String("container_name", containerName))
	}

	v.logger.Info("Dry-run validation with limits completed",
		slog.String("instance_id", instance.InstanceID),
		slog.Bool("valid", result.Valid),
		slog.Int("errors", len(result.Errors)),
		slog.Int("warnings", len(result.Warnings)))

	return result, nil
}

// validateJSONSpec validates the structure of json_spec
func (v *ContainerValidator) validateJSONSpec(jsonSpec map[string]interface{}) error {
	required := []string{"image", "port"}
	for _, field := range required {
		if _, exists := jsonSpec[field]; !exists {
			return fmt.Errorf("required field %s is missing", field)
		}
	}

	// Validate image field
	if image, ok := jsonSpec["image"].(string); !ok || image == "" {
		return fmt.Errorf("image field must be a non-empty string")
	}

	// Validate port field
	switch port := jsonSpec["port"].(type) {
	case int:
		if port < 1 || port > 65535 {
			return fmt.Errorf("port must be between 1 and 65535")
		}
	case float64:
		if port < 1 || port > 65535 {
			return fmt.Errorf("port must be between 1 and 65535")
		}
	default:
		return fmt.Errorf("port field must be a number")
	}

	// Validate environment variables if present
	if env, exists := jsonSpec["environment"]; exists {
		if _, ok := env.(map[string]interface{}); !ok {
			return fmt.Errorf("environment field must be an object")
		}
	}

	// Validate command if present
	if cmd, exists := jsonSpec["cmd"]; exists {
		if _, ok := cmd.([]interface{}); !ok {
			return fmt.Errorf("cmd field must be an array")
		}
	}

	return nil
}

// validateResourceRequirements validates resource requirements
func (v *ContainerValidator) validateResourceRequirements(jsonSpec map[string]interface{}) error {
	resources, exists := jsonSpec["resources"]
	if !exists {
		return nil // Resources are optional
	}

	resourceMap, ok := resources.(map[string]interface{})
	if !ok {
		return fmt.Errorf("resources must be an object")
	}

	// Validate memory limit
	if memLimit, exists := resourceMap["memory_limit"]; exists {
		if _, ok := memLimit.(string); !ok {
			return fmt.Errorf("memory_limit must be a string")
		}
		// Could add more validation for memory format (e.g., "256m", "1g")
	}

	// Validate CPU limit
	if cpuLimit, exists := resourceMap["cpu_limit"]; exists {
		if _, ok := cpuLimit.(string); !ok {
			return fmt.Errorf("cpu_limit must be a string")
		}
		// Could add more validation for CPU format (e.g., "0.5", "1.0")
	}

	return nil
}

// PullImageWithProgress pulls an image with progress tracking
func (v *ContainerValidator) PullImageWithProgress(ctx context.Context, imageName string, progressCallback func(string)) error {
	v.logger.Info("Pulling image with progress tracking",
		slog.String("image", imageName))

	cmd := exec.CommandContext(ctx, "podman", "pull", imageName)

	// Create a pipe to capture output
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return fmt.Errorf("failed to create stdout pipe: %w", err)
	}

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("failed to start pull command: %w", err)
	}

	// Read progress in a goroutine
	go func() {
		buf := make([]byte, 1024)
		for {
			n, err := stdout.Read(buf)
			if err != nil {
				break
			}
			if progressCallback != nil {
				progressCallback(string(buf[:n]))
			}
		}
	}()

	if err := cmd.Wait(); err != nil {
		return fmt.Errorf("failed to pull image: %w", err)
	}

	v.logger.Info("Image pulled successfully",
		slog.String("image", imageName))

	return nil
}

// GetContainerStatus gets detailed container status
func (v *ContainerValidator) GetContainerStatus(ctx context.Context, containerID string) (*models.DetailedContainerStatus, error) {
	cmd := exec.CommandContext(ctx, "podman", "inspect", containerID, "--format", "json")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return nil, fmt.Errorf("failed to inspect container: %w", err)
	}

	var inspectData []map[string]interface{}
	if err := json.Unmarshal(output, &inspectData); err != nil {
		return nil, fmt.Errorf("failed to parse inspect output: %w", err)
	}

	if len(inspectData) == 0 {
		return nil, fmt.Errorf("no container data found")
	}

	container := inspectData[0]
	state, ok := container["State"].(map[string]interface{})
	if !ok {
		return nil, fmt.Errorf("no state information found")
	}

	status := &models.DetailedContainerStatus{
		Status:     state["Status"].(string),
		Running:    state["Running"].(bool),
		Paused:     state["Paused"].(bool),
		Restarting: state["Restarting"].(bool),
		OOMKilled:  state["OOMKilled"].(bool),
		Dead:       state["Dead"].(bool),
		Pid:        int(state["Pid"].(float64)),
		ExitCode:   int(state["ExitCode"].(float64)),
		Error:      state["Error"].(string),
		StartedAt:  state["StartedAt"].(string),
		FinishedAt: state["FinishedAt"].(string),
	}

	return status, nil
}
