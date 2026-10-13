package backends

import (
	"context"
	"fmt"

	"k8s.io/apimachinery/pkg/api/resource"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/container"
)

// Reservation is what a workload holds on its host whether it is busy or idle: per
// dimension its request, else its limit. It is the amount compute billing charges
// for, so a price shown ahead of time is computed from it. Zero is a dimension the
// workload does not reserve.
type Reservation struct {
	CPUMillicores int64 `json:"cpu_millicores"`
	MemoryBytes   int64 `json:"memory_bytes"`
}

// DefaultReservationReporter is a backend that can say what a new MCP instance
// whose spec names no resources reserves. Optional: a backend that cannot say
// leaves the reservation unknown rather than guessed.
type DefaultReservationReporter interface {
	DefaultReservation(ctx context.Context) (Reservation, error)
}

// DefaultReservation is the request a pod is created with when its spec names
// none, else its limit, as Kubernetes itself reserves it.
func (k *KubernetesBackend) DefaultReservation(context.Context) (Reservation, error) {
	return kubernetesReservation(k.k8sConfig.GetResourceRequirements(nil, nil), k.k8sConfig.GetResourceLimits(nil))
}

func kubernetesReservation(requests, limits config.ResourceRequirements) (Reservation, error) {
	cpu, err := firstQuantity(requests.CPU, limits.CPU)
	if err != nil {
		return Reservation{}, fmt.Errorf("cpu: %w", err)
	}
	memory, err := firstQuantity(requests.Memory, limits.Memory)
	if err != nil {
		return Reservation{}, fmt.Errorf("memory: %w", err)
	}
	return Reservation{CPUMillicores: cpu.MilliValue(), MemoryBytes: memory.Value()}, nil
}

func firstQuantity(values ...string) (resource.Quantity, error) {
	for _, value := range values {
		if value != "" {
			return resource.ParseQuantity(value)
		}
	}
	return resource.Quantity{}, nil
}

// DefaultReservation is the limit a container is started with when its spec names
// none: Docker reserves no request, so the limit is what billing charges for.
func (d *DockerBackend) DefaultReservation(context.Context) (Reservation, error) {
	cpu, memory, err := container.DefaultLimits(d.config.Container)
	if err != nil {
		return Reservation{}, err
	}
	return Reservation{CPUMillicores: cpu, MemoryBytes: memory}, nil
}
