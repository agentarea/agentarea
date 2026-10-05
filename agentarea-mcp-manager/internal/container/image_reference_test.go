package container

import (
	"context"
	"strings"
	"testing"

	"github.com/agentarea/mcp-manager/internal/models"
)

func TestValidateImageReferenceAcceptsRealReferences(t *testing.T) {
	for _, image := range []string{
		"alpine",
		"alpine:3.20",
		"mcp/fetch",
		"ghcr.io/github/github-mcp-server:latest",
		"registry.example.com:5000/team/server:v1.2.3",
		"localhost:5000/server",
		"python@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
		"agentarea/mcp-base:dev",
	} {
		if err := ValidateImageReference(image); err != nil {
			t.Errorf("ValidateImageReference(%q) = %v, want nil", image, err)
		}
	}
}

// The image sits in the flag position of `docker run`; a value the runtime
// can read as a flag hands the container the host.
func TestValidateImageReferenceRefusesRuntimeFlags(t *testing.T) {
	for _, image := range []string{
		"--volume=/var/run/docker.sock:/var/run/docker.sock",
		"--privileged",
		"-v/:/host",
		"alpine --privileged",
		"alpine\n--privileged",
		"",
	} {
		if err := ValidateImageReference(image); err == nil {
			t.Errorf("ValidateImageReference(%q) = nil, want an error", image)
		}
	}
}

func TestCreateContainerRefusesAFlagShapedImageBeforeTheRuntime(t *testing.T) {
	runtime, logPath := stubRuntime(t)
	t.Setenv("STUB_INSPECT_RC", "1")
	manager := &Manager{config: testConfig(runtime), logger: discardLogger(), containers: map[string]*models.Container{}}

	_, err := manager.CreateContainer(context.Background(), models.CreateContainerRequest{
		ServiceName: "escape",
		Image:       "--volume=/var/run/docker.sock:/var/run/docker.sock",
		Command:     []string{"docker:cli", "sh"},
		Port:        8080,
	})
	if err == nil {
		t.Fatal("CreateContainer() error = nil, want the image refused")
	}
	if calls := stubCalls(t, logPath); strings.Contains(calls, "run -d") {
		t.Fatalf("a refused image still reached the runtime:\n%s", calls)
	}
}
