package models

import (
	"time"
)

// ContainerStatus represents the status of a container
type ContainerStatus string

const (
	StatusValidating ContainerStatus = "validating"
	StatusPulling    ContainerStatus = "pulling"
	StatusStopped    ContainerStatus = "stopped"
	StatusStarting   ContainerStatus = "starting"
	StatusRunning    ContainerStatus = "running"
	StatusStopping   ContainerStatus = "stopping"
	StatusError      ContainerStatus = "error"
	StatusHealthy    ContainerStatus = "healthy"
	StatusUnhealthy  ContainerStatus = "unhealthy"
)

// DetailedContainerStatus represents detailed container status information
type DetailedContainerStatus struct {
	Status     string `json:"status"`
	Running    bool   `json:"running"`
	Paused     bool   `json:"paused"`
	Restarting bool   `json:"restarting"`
	OOMKilled  bool   `json:"oom_killed"`
	Dead       bool   `json:"dead"`
	Pid        int    `json:"pid"`
	ExitCode   int    `json:"exit_code"`
	Error      string `json:"error"`
	StartedAt  string `json:"started_at"`
	FinishedAt string `json:"finished_at"`
}

// Container represents a managed container
type Container struct {
	ID          string            `json:"id"`
	Name        string            `json:"name"`
	ServiceName string            `json:"service_name"`
	Slug        string            `json:"slug"`
	Image       string            `json:"image"`
	Status      ContainerStatus   `json:"status"`
	Port        int               `json:"port"`
	URL         string            `json:"url,omitempty"`
	Host        string            `json:"host,omitempty"`
	CreatedAt   time.Time         `json:"created_at"`
	UpdatedAt   time.Time         `json:"updated_at"`
	Labels      map[string]string `json:"labels,omitempty"`
	Environment map[string]string `json:"environment,omitempty"`
	Command     []string          `json:"command,omitempty"`
}

// VolumeMount represents a volume mount
type VolumeMount struct {
	Source      string `json:"source"`
	Destination string `json:"destination"`
	ReadOnly    bool   `json:"read_only,omitempty"`
}

// CreateContainerRequest represents a request to create a new container
type CreateContainerRequest struct {
	ServiceName string            `json:"service_name" binding:"required"`
	Image       string            `json:"image" binding:"required"`
	Port        int               `json:"port" binding:"required"`
	Environment map[string]string `json:"environment,omitempty"`
	Labels      map[string]string `json:"labels,omitempty"`
	Command     []string          `json:"command,omitempty"`
	Volumes     []VolumeMount     `json:"volumes,omitempty"`
	MemoryLimit string            `json:"memory_limit,omitempty"`
	CPULimit    string            `json:"cpu_limit,omitempty"`
}

// HealthResponse represents the health check response
type HealthResponse struct {
	Status            string    `json:"status"`
	Version           string    `json:"version"`
	ContainersRunning int       `json:"containers_running"`
	Timestamp         time.Time `json:"timestamp"`
	Uptime            string    `json:"uptime,omitempty"`
}

// MCPEnvVar represents an environment variable for an MCP provider
type MCPEnvVar struct {
	Name        string `json:"name" yaml:"name"`
	Description string `json:"description" yaml:"description"`
	Required    bool   `json:"required" yaml:"required"`
	Default     string `json:"default,omitempty" yaml:"default,omitempty"`
	Secret      bool   `json:"secret,omitempty" yaml:"secret,omitempty"`
}

// MCPProviderTemplate represents an MCP provider template
type MCPProviderTemplate struct {
	ID           string      `json:"id" yaml:"id"`
	Name         string      `json:"name" yaml:"name"`
	Description  string      `json:"description" yaml:"description"`
	Icon         string      `json:"icon" yaml:"icon"`
	DockerImage  string      `json:"docker_image" yaml:"docker_image"`
	EnvVars      []MCPEnvVar `json:"env_vars" yaml:"env_vars"`
	Capabilities []string    `json:"capabilities" yaml:"capabilities"`
}

// MCPProviderList represents the list of MCP providers from YAML
type MCPProviderList struct {
	Providers map[string]MCPProviderTemplate `json:"providers" yaml:"providers"`
}

// ListContainersResponse represents the response for listing containers
type ListContainersResponse struct {
	Containers []Container `json:"containers"`
	Total      int         `json:"total"`
}

// ErrorResponse represents an error response
type ErrorResponse struct {
	Error   string `json:"error"`
	Code    int    `json:"code"`
	Message string `json:"message"`
}

// MCPServerInstance represents an MCP server instance from events
type MCPServerInstance struct {
	InstanceID   string                 `json:"instance_id"`
	Name         string                 `json:"name"`
	Description  string                 `json:"description,omitempty"`
	ServerSpecID string                 `json:"server_spec_id,omitempty"`
	JSONSpec     map[string]interface{} `json:"json_spec"`
	Status       string                 `json:"status"`
}

// MCPEventData represents the data structure from Redis events
type MCPEventData struct {
	InstanceID   string                 `json:"instance_id"`
	Name         string                 `json:"name"`
	Description  string                 `json:"description,omitempty"`
	ServerSpecID string                 `json:"server_spec_id,omitempty"`
	JSONSpec     map[string]interface{} `json:"json_spec"`
}
