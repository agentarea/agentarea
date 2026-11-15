package docker

import (
	"slices"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/runtime/workload"
)

func TestIsolationRunArgsRendersEachSetting(t *testing.T) {
	args := isolationRunArgs(workload.Isolation{
		Runtime:                "runsc",
		DropCapabilities:       []string{"ALL"},
		NoNewPrivileges:        true,
		ReadOnlyRootFilesystem: true,
		WritablePaths:          []string{"/tmp", "/var/run"},
		PidsLimit:              256,
		User:                   "10001:10001",
	})
	for _, want := range [][2]string{
		{"--runtime", "runsc"},
		{"--cap-drop", "ALL"},
		{"--security-opt", "no-new-privileges"},
		{"--pids-limit", "256"},
		{"--user", "10001:10001"},
		{"--tmpfs", "/tmp:rw,nosuid,nodev"},
		{"--tmpfs", "/var/run:rw,nosuid,nodev"},
	} {
		if !hasFlagPair(args, want[0], want[1]) {
			t.Errorf("missing %s %s in %v", want[0], want[1], args)
		}
	}
	if !slices.Contains(args, "--read-only") {
		t.Errorf("missing --read-only in %v", args)
	}
}

func TestIsolationRunArgsEmptyForZeroValue(t *testing.T) {
	if args := isolationRunArgs(workload.Isolation{}); len(args) != 0 {
		t.Errorf("zero isolation rendered %v", args)
	}
}

func TestIsolationRunArgsOmitsTmpfsWithoutReadOnlyRoot(t *testing.T) {
	args := isolationRunArgs(workload.Isolation{WritablePaths: []string{"/tmp"}})
	if slices.Contains(args, "--tmpfs") {
		t.Errorf("tmpfs without a read-only root: %v", args)
	}
}

func TestRunArgsPreferTheCeilingTheWorkloadAskedFor(t *testing.T) {
	cfg := testConfig()
	asked := strings.Join(cfg.runArgs(container{name: "asked", image: "vendor/mcp:1.0", memory: "2g", cpu: "2.0"}), " ")
	if !strings.Contains(asked, "--memory 2g") || !strings.Contains(asked, "--cpus 2.0") {
		t.Fatalf("run args ignored the requested ceiling: %s", asked)
	}
	silent := strings.Join(cfg.runArgs(container{name: "silent", image: "vendor/mcp:1.0"}), " ")
	if !strings.Contains(silent, "--memory 512m") || !strings.Contains(silent, "--cpus 1.0") {
		t.Fatalf("run args dropped the host default: %s", silent)
	}
}

func TestSpecOwnershipComesFromTheInstanceNotTheCallerLabels(t *testing.T) {
	cfg := testConfig()
	ct, err := cfg.fromSpec(workload.Spec{
		Name: "i-1", ServiceName: "i-1", InstanceID: "i-1", WorkspaceID: "ws-1",
		Image: "vendor/mcp:1.0", Port: 8080,
		Labels: map[string]string{ownerLabel: "someone-else", instanceLabel: "forged", "agentarea.io/egress": "x"},
	})
	if err != nil {
		t.Fatal(err)
	}
	args := cfg.runArgs(ct)
	if slices.Contains(args, ownerLabel+"=someone-else") || slices.Contains(args, instanceLabel+"=forged") {
		t.Fatalf("a caller label claimed ownership: %v", args)
	}
	for _, want := range []string{ownerLabel + "=i-1", instanceLabel + "=i-1", workspaceLabel + "=ws-1", "agentarea.io/egress=x"} {
		if !hasFlagPair(args, "--label", want) {
			t.Errorf("missing label %s in %v", want, args)
		}
	}
	for _, want := range []string{"MCP_INSTANCE_ID=i-1", "MCP_SERVICE_NAME=i-1", "MCP_CONTAINER_PORT=8080"} {
		if !hasFlagPair(args, "-e", want) {
			t.Errorf("missing env %s in %v", want, args)
		}
	}
	if !hasFlagPair(args, "--name", "mcp-i-1") || !hasFlagPair(args, "--network", "agentarea-mcp") {
		t.Errorf("name or network missing: %v", args)
	}
	if !slices.Contains(args, "--cap-drop") {
		t.Errorf("the default tier was not applied: %v", args)
	}
}

func TestEntrypointBecomesTheRuntimeEntrypointAndLeadsTheCommand(t *testing.T) {
	cfg := testConfig()
	args := cfg.runArgs(container{name: "n", image: "img:1", entrypoint: []string{"/bin/sh", "-c"}, command: []string{"serve"}})
	if !hasFlagPair(args, "--entrypoint", "/bin/sh") || !slices.Equal(args[len(args)-3:], []string{"img:1", "-c", "serve"}) {
		t.Fatalf("entrypoint not rendered: %v", args)
	}
}

func TestContainerNameSanitizesTheServiceName(t *testing.T) {
	cfg := testConfig()
	for in, want := range map[string]string{
		"Weather Server": "mcp-weather-server",
		"--x--":          "mcp-x",
		"!!!":            "mcp-container-",
		"6f1c-AB":        "mcp-6f1c-ab",
	} {
		if got := cfg.ContainerName(in); got != want {
			t.Errorf("ContainerName(%q) = %q, want %q", in, got, want)
		}
	}
}
