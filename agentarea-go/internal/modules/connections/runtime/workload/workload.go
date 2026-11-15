// Package workload is what an MCP workload backend runs: the spec the runtime
// builds, the status a backend reports, and the Backend port the docker,
// kubernetes and dataplane backends implement. Its JSON is the dataplane wire
// format, so the control plane and a remote host speak the same shapes.
package workload

import (
	"context"
	"errors"
)

// ErrNotFound is a workload the backend does not run.
var ErrNotFound = errors.New("mcp workload not found")

// Workload states a backend reports.
const (
	StatusStarting = "starting"
	StatusRunning  = "running"
	StatusStopped  = "stopped"
)

// Backend runs MCP workloads. Create is an acknowledgment: the workload may
// still be starting when it returns, and the runtime polls Status until it runs.
type Backend interface {
	// Create starts the workload; creating one that already runs is not an error.
	Create(ctx context.Context, spec Spec) (Status, error)
	// Delete removes the workload; removing one that does not exist is not an error.
	Delete(ctx context.Context, instanceID string) error
	// Status reports the workload, or ErrNotFound.
	Status(ctx context.Context, instanceID string) (Status, error)
	// Reservation is what one workload of the default size reserves on the host.
	Reservation(ctx context.Context) (Reservation, error)
}

// Spec is one MCP workload.
type Spec struct {
	Name          string            `json:"name"`
	Image         string            `json:"image"`
	Port          int               `json:"port"`
	Environment   map[string]string `json:"environment,omitempty"`
	Labels        map[string]string `json:"labels,omitempty"`
	Entrypoint    []string          `json:"entrypoint,omitempty"`
	Command       []string          `json:"command,omitempty"`
	Resources     Resources         `json:"resources,omitzero"`
	WritablePaths []string          `json:"writable_paths,omitempty"`
	RuntimeClass  string            `json:"runtime_class,omitempty"`
	IsolationTier string            `json:"isolation_tier,omitempty"`
	InstanceID    string            `json:"instance_id"`
	WorkspaceID   string            `json:"workspace_id,omitempty"`
	ServiceName   string            `json:"service_name"`
}

// Resources are the requests and limits of a workload.
type Resources struct {
	Requests ResourceList `json:"requests,omitzero"`
	Limits   ResourceList `json:"limits,omitzero"`
}

// ResourceList is a CPU and memory quantity pair.
type ResourceList struct {
	CPU    string `json:"cpu,omitempty"`
	Memory string `json:"memory,omitempty"`
}

// Status is a workload as its backend sees it. Message carries the workload's
// own startup output when it stopped, already redacted by the backend.
type Status struct {
	ID          string            `json:"id"`
	Name        string            `json:"name"`
	Status      string            `json:"status"`
	InternalURL string            `json:"internal_url,omitempty"`
	Port        int               `json:"port"`
	Labels      map[string]string `json:"labels,omitempty"`
	Message     string            `json:"message,omitempty"`
}

// Reservation is the CPU and memory one default workload reserves.
type Reservation struct {
	CPUMillicores int64 `json:"cpu_millicores"`
	MemoryBytes   int64 `json:"memory_bytes"`
}
