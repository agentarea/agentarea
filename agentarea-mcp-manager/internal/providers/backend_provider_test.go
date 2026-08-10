package providers

import (
	"io"
	"log/slog"
	"testing"

	"github.com/agentarea/mcp-manager/internal/models"
)

func newTestBackendProvider() *BackendProvider {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	return &BackendProvider{backend: nil, logger: logger}
}

// command-type: image must be the sandbox bridge, port must be 8080, and
// Command must equal [cmd, ...args] (no filtering needed since stdio is not
// relevant to the bridge wrapper).
func TestConvertToInstanceSpec_CommandType_UsesSandboxImageAndPort(t *testing.T) {
	p := newTestBackendProvider()

	instance := &models.MCPServerInstance{
		InstanceID: "inst-1",
		Name:       "my-cmd-server",
		JSONSpec: map[string]interface{}{
			"type":    "command",
			"command": "npx",
			"args":    []interface{}{"-y", "@modelcontextprotocol/server-filesystem", "/data"},
		},
	}

	spec := p.convertToInstanceSpec(instance)

	if spec.Image != sandboxImage {
		t.Errorf("expected Image=%q, got %q", sandboxImage, spec.Image)
	}
	if spec.Port != sandboxPort {
		t.Errorf("expected Port=%d, got %d", sandboxPort, spec.Port)
	}

	wantCmd := []string{"npx", "-y", "@modelcontextprotocol/server-filesystem", "/data"}
	if len(spec.Command) != len(wantCmd) {
		t.Fatalf("expected Command length %d, got %d: %v", len(wantCmd), len(spec.Command), spec.Command)
	}
	for i, v := range wantCmd {
		if spec.Command[i] != v {
			t.Errorf("Command[%d]: expected %q, got %q", i, v, spec.Command[i])
		}
	}
}

// command-type: spec.Command is built from json_spec["command"] (a string,
// not a slice). The field maps to spec.Command directly, not spec.Entrypoint.
func TestConvertToInstanceSpec_CommandType_CommandFieldIsString(t *testing.T) {
	p := newTestBackendProvider()

	instance := &models.MCPServerInstance{
		InstanceID: "inst-2",
		Name:       "my-cmd-simple",
		JSONSpec: map[string]interface{}{
			"type":    "command",
			"command": "uvx",
			"args":    []interface{}{"mcp-server-git"},
		},
	}

	spec := p.convertToInstanceSpec(instance)

	if spec.Image != sandboxImage {
		t.Errorf("expected Image=%q, got %q", sandboxImage, spec.Image)
	}
	if len(spec.Command) < 1 || spec.Command[0] != "uvx" {
		t.Errorf("expected Command[0]=%q, got %v", "uvx", spec.Command)
	}
}

// docker-type: --transport=stdio must be stripped from Command; all other
// flags must be preserved unchanged.
func TestConvertToInstanceSpec_DockerType_StripTransportStdioFlag(t *testing.T) {
	p := newTestBackendProvider()

	instance := &models.MCPServerInstance{
		InstanceID: "inst-3",
		Name:       "postgres-mcp",
		JSONSpec: map[string]interface{}{
			"type":    "docker",
			"image":   "crystaldba/postgres-mcp:latest",
			"port":    float64(8080),
			"command": []interface{}{"--transport=stdio", "--connection-string=postgres://localhost/db"},
		},
	}

	spec := p.convertToInstanceSpec(instance)

	for _, arg := range spec.Command {
		if arg == "--transport=stdio" {
			t.Errorf("--transport=stdio must be stripped from Command, but found it in: %v", spec.Command)
		}
	}

	found := false
	for _, arg := range spec.Command {
		if arg == "--connection-string=postgres://localhost/db" {
			found = true
			break
		}
	}
	if !found {
		t.Errorf("expected --connection-string flag to be preserved, got: %v", spec.Command)
	}
}

// docker-type without --transport=stdio: command passes through unchanged.
func TestConvertToInstanceSpec_DockerType_NoStdioFlag_CommandUnchanged(t *testing.T) {
	p := newTestBackendProvider()

	instance := &models.MCPServerInstance{
		InstanceID: "inst-4",
		Name:       "no-stdio-server",
		JSONSpec: map[string]interface{}{
			"type":    "docker",
			"image":   "myorg/mcp-server:v1",
			"port":    float64(3000),
			"command": []interface{}{"--port=3000", "--verbose"},
		},
	}

	spec := p.convertToInstanceSpec(instance)

	want := []string{"--port=3000", "--verbose"}
	if len(spec.Command) != len(want) {
		t.Fatalf("expected Command=%v, got %v", want, spec.Command)
	}
	for i, v := range want {
		if spec.Command[i] != v {
			t.Errorf("Command[%d]: expected %q, got %q", i, v, spec.Command[i])
		}
	}
}

// docker-type: image and port are taken from json_spec, not overridden with
// the sandbox values.
func TestConvertToInstanceSpec_DockerType_UsesImageAndPortFromSpec(t *testing.T) {
	p := newTestBackendProvider()

	instance := &models.MCPServerInstance{
		InstanceID: "inst-5",
		Name:       "custom-image-server",
		JSONSpec: map[string]interface{}{
			"type":  "docker",
			"image": "myorg/custom-mcp:2.0",
			"port":  float64(9090),
		},
	}

	spec := p.convertToInstanceSpec(instance)

	if spec.Image != "myorg/custom-mcp:2.0" {
		t.Errorf("expected Image=%q, got %q", "myorg/custom-mcp:2.0", spec.Image)
	}
	if spec.Port != 9090 {
		t.Errorf("expected Port=9090, got %d", spec.Port)
	}
	if spec.Image == sandboxImage {
		t.Errorf("docker-type must NOT use sandboxImage %q", sandboxImage)
	}
}

// docker-type with --transport=stdio as the only command arg results in an
// empty (nil or zero-length) Command slice.
func TestConvertToInstanceSpec_DockerType_OnlyStdioFlag_CommandBecomesEmpty(t *testing.T) {
	p := newTestBackendProvider()

	instance := &models.MCPServerInstance{
		InstanceID: "inst-6",
		Name:       "stdio-only-server",
		JSONSpec: map[string]interface{}{
			"type":    "docker",
			"image":   "some/mcp:latest",
			"port":    float64(8000),
			"command": []interface{}{"--transport=stdio"},
		},
	}

	spec := p.convertToInstanceSpec(instance)

	if len(spec.Command) != 0 {
		t.Errorf("expected empty Command after stripping --transport=stdio, got %v", spec.Command)
	}
}

// The provider must not decide the isolation tier. Pinning "untrusted" here
// asked every MCP pod for a syscall-interposing RuntimeClass; on a cluster
// without one the pod stayed Pending, the gateway's cold start timed out, and
// the instance was unreachable no matter what it ran. Leaving the field empty
// hands the decision to the operator's DEFAULT_ISOLATION_TIER.
func TestConvertToInstanceSpecLeavesTheIsolationTierToTheOperator(t *testing.T) {
	p := newTestBackendProvider()

	for name, jsonSpec := range map[string]map[string]interface{}{
		"docker":  {"type": "docker", "image": "ghcr.io/vendor/mcp:1.0", "port": 9000},
		"command": {"type": "command", "command": "mcp-server-notion"},
	} {
		t.Run(name, func(t *testing.T) {
			spec := p.convertToInstanceSpec(&models.MCPServerInstance{
				InstanceID: "inst-1",
				Name:       "server",
				JSONSpec:   jsonSpec,
			})
			if spec.IsolationTier != "" {
				t.Fatalf("IsolationTier = %q; the provider pinned a tier the cluster may not be able to satisfy", spec.IsolationTier)
			}
		})
	}
}
