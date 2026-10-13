package backends

import (
	"testing"

	"github.com/agentarea/mcp-manager/internal/config"
)

// The request is what a pod reserves; a dimension without one reserves its limit.
func TestKubernetesReservationIsTheRequestElseTheLimit(t *testing.T) {
	got, err := kubernetesReservation(
		config.ResourceRequirements{CPU: "100m"},
		config.ResourceRequirements{CPU: "500m", Memory: "512Mi"},
	)
	if err != nil {
		t.Fatal(err)
	}
	want := Reservation{CPUMillicores: 100, MemoryBytes: 512 * 1024 * 1024}
	if got != want {
		t.Fatalf("got %+v, want %+v", got, want)
	}
}

func TestKubernetesReservationRefusesAnUnparsableQuantity(t *testing.T) {
	if _, err := kubernetesReservation(config.ResourceRequirements{CPU: "lots"}, config.ResourceRequirements{}); err == nil {
		t.Fatal("got no error for an unparsable cpu request")
	}
}

// Docker reserves no request, so its default limits are the reservation, read in
// Docker's own syntax: cpus as a fraction, memory with a binary suffix.
func TestDockerReservationIsTheDefaultLimit(t *testing.T) {
	backend := &DockerBackend{config: &config.Config{Container: config.ContainerConfig{
		DefaultCPULimit:    "1.0",
		DefaultMemoryLimit: "512m",
	}}}
	got, err := backend.DefaultReservation(t.Context())
	if err != nil {
		t.Fatal(err)
	}
	want := Reservation{CPUMillicores: 1000, MemoryBytes: 512 * 1024 * 1024}
	if got != want {
		t.Fatalf("got %+v, want %+v", got, want)
	}
}
