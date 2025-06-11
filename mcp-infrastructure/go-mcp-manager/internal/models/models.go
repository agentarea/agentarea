package models

import (
	"time"
)

// ContainerStatus represents the status of a container
type ContainerStatus string

const (
	StatusStopped  ContainerStatus = "stopped"
	StatusStarting ContainerStatus = "starting"
	StatusRunning  ContainerStatus = "running"
	StatusStopping ContainerStatus = "stopping"
	StatusError    ContainerStatus = "error"
)

// Container represents a managed container
type Container struct {
	ID          string            `json:"id"`
	Name        string            `json:"name"`
	ServiceName string            `json:"service_name"`
	Image       string            `json:"image"`
	Status      ContainerStatus   `json:"status"`
	Port        int               `json:"port"`
	URL         string            `json:"url,omitempty"`
	Host        string            `json:"host,omitempty"`
	CreatedAt   time.Time         `json:"created_at"`
	UpdatedAt   time.Time         `json:"updated_at"`
	Labels      map[string]string `json:"labels,omitempty"`
	Environment map[string]string `json:"environment,omitempty"`
}

// Template represents a container template
type Template struct {
	Name        string            `json:"name"`
	Description string            `json:"description"`
	Image       string            `json:"image"`
	Port        int               `json:"port"`
	Environment map[string]string `json:"environment,omitempty"`
	Labels      map[string]string `json:"labels,omitempty"`
	Command     []string          `json:"command,omitempty"`
	Volumes     []VolumeMount     `json:"volumes,omitempty"`
	MemoryLimit string            `json:"memory_limit,omitempty"`
	CPULimit    string            `json:"cpu_limit,omitempty"`
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
	Template    string            `json:"template" binding:"required"`
	Environment map[string]string `json:"environment,omitempty"`
	Labels      map[string]string `json:"labels,omitempty"`
}

// HealthResponse represents the health check response
type HealthResponse struct {
	Status            string    `json:"status"`
	Version           string    `json:"version"`
	ContainersRunning int       `json:"containers_running"`
	Timestamp         time.Time `json:"timestamp"`
	Uptime            string    `json:"uptime,omitempty"`
}

// ListContainersResponse represents the response for listing containers
type ListContainersResponse struct {
	Containers []Container `json:"containers"`
	Total      int         `json:"total"`
}

// ListTemplatesResponse represents the response for listing templates
type ListTemplatesResponse struct {
	Templates []Template `json:"templates"`
	Total     int        `json:"total"`
}

// ErrorResponse represents an error response
type ErrorResponse struct {
	Error   string `json:"error"`
	Code    int    `json:"code"`
	Message string `json:"message"`
}

// CaddyStatusResponse represents Caddy status
type CaddyStatusResponse struct {
	Status      string   `json:"status"`
	RoutesCount int      `json:"routes_count"`
	Services    []string `json:"services"`
	APIURL      string   `json:"api_url"`
	CaddyHost   string   `json:"caddy_host"`
}

// CaddyRoute represents a Caddy route configuration
type CaddyRoute struct {
	Match  []CaddyMatch  `json:"match"`
	Handle []CaddyHandle `json:"handle"`
}

// CaddyMatch represents a Caddy route match condition
type CaddyMatch struct {
	Host []string `json:"host,omitempty"`
	Path []string `json:"path,omitempty"`
}

// CaddyHandle represents a Caddy route handler
type CaddyHandle struct {
	Handler   string          `json:"handler"`
	Upstreams []CaddyUpstream `json:"upstreams,omitempty"`
}

// CaddyUpstream represents a Caddy upstream
type CaddyUpstream struct {
	Dial string `json:"dial"`
}
