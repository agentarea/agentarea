package backends

import (
	"context"
	"time"
)

// Backend defines the interface for container management backends (Docker/Kubernetes)
type Backend interface {
	// CreateInstance creates a new MCP server instance
	CreateInstance(ctx context.Context, spec *InstanceSpec) (*InstanceResult, error)

	// DeleteInstance removes an MCP server instance
	DeleteInstance(ctx context.Context, instanceID string) error

	// GetInstanceStatus retrieves the current status of an instance
	GetInstanceStatus(ctx context.Context, instanceID string) (*InstanceStatus, error)

	// ListInstances returns all managed instances
	ListInstances(ctx context.Context) ([]*InstanceStatus, error)

	// UpdateInstance updates an existing instance configuration
	UpdateInstance(ctx context.Context, instanceID string, spec *InstanceSpec) error

	// PerformHealthCheck performs health check on an instance
	PerformHealthCheck(ctx context.Context, instanceID string) (*HealthCheckResult, error)

	// Initialize initializes the backend
	Initialize(ctx context.Context) error

	// Shutdown gracefully shuts down the backend
	Shutdown(ctx context.Context) error
}

// InstanceSpec defines the specification for creating an MCP server instance
type InstanceSpec struct {
	// Basic information
	Name  string `json:"name"`
	Image string `json:"image"`
	Port  int    `json:"port"`

	// Configuration
	Environment map[string]string `json:"environment,omitempty"`
	Labels      map[string]string `json:"labels,omitempty"`
	Command     []string          `json:"command,omitempty"`

	// Resource requirements
	Resources ResourceRequirements `json:"resources,omitempty"`

	// Networking
	ExposedPort int `json:"exposed_port,omitempty"`

	// Volume mounts for writable directories (security sandbox)
	WritablePaths []string `json:"writable_paths,omitempty"`

	// Metadata
	InstanceID  string `json:"instance_id"`
	WorkspaceID string `json:"workspace_id,omitempty"`
	ServiceName string `json:"service_name"`
}

// ResourceRequirements defines resource constraints for instances
type ResourceRequirements struct {
	Requests ResourceList `json:"requests,omitempty"`
	Limits   ResourceList `json:"limits,omitempty"`
}

type ResourceList struct {
	CPU    string `json:"cpu,omitempty"`
	Memory string `json:"memory,omitempty"`
}

// InstanceResult represents the result of creating an instance
type InstanceResult struct {
	ID          string    `json:"id"`
	Name        string    `json:"name"`
	URL         string    `json:"url"`
	InternalURL string    `json:"internal_url,omitempty"`
	Status      string    `json:"status"`
	CreatedAt   time.Time `json:"created_at"`
}

// InstanceStatus represents the current status of an instance
type InstanceStatus struct {
	ID           string             `json:"id"`
	Name         string             `json:"name"`
	ServiceName  string             `json:"service_name"`
	Status       string             `json:"status"`
	URL          string             `json:"url,omitempty"`
	InternalURL  string             `json:"internal_url,omitempty"`
	Image        string             `json:"image"`
	Port         int                `json:"port"`
	Environment  map[string]string  `json:"environment,omitempty"`
	Labels       map[string]string  `json:"labels,omitempty"`
	CreatedAt    time.Time          `json:"created_at"`
	UpdatedAt    time.Time          `json:"updated_at"`
	HealthStatus *HealthCheckResult `json:"health_status,omitempty"`
}

// HealthCheckResult represents the result of a health check
type HealthCheckResult struct {
	Healthy       bool          `json:"healthy"`
	Status        string        `json:"status"`
	HTTPReachable bool          `json:"http_reachable"`
	ResponseTime  time.Duration `json:"response_time"`
	ContainerID   string        `json:"container_id,omitempty"`
	ServiceName   string        `json:"service_name"`
	Error         string        `json:"error,omitempty"`
	Details       interface{}   `json:"details,omitempty"`
	Timestamp     time.Time     `json:"timestamp"`
}

// BackendType represents the type of backend
type BackendType string

const (
	BackendTypeDocker     BackendType = "docker"
	BackendTypeKubernetes BackendType = "kubernetes"
)

// BackendFactory creates backend instances based on configuration
type BackendFactory interface {
	CreateBackend(backendType BackendType) (Backend, error)
}
