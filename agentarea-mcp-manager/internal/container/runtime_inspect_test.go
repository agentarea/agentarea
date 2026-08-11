package container

import (
	"bytes"
	"context"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/models"
)

// stubRuntime writes a fake container runtime whose inspect behaviour is steered
// by environment variables, so the call sequence can be asserted without Docker.
func stubRuntime(t *testing.T) (path string, logPath string) {
	t.Helper()

	dir := t.TempDir()
	path = filepath.Join(dir, "runtime")
	logPath = filepath.Join(dir, "calls.log")

	script := `#!/bin/sh
printf '%s\n' "$*" >> "$STUB_LOG"
if [ "$1" = "inspect" ]; then
  case "$4" in
    *State.Running*)
      if [ -n "$STUB_RUNNING" ]; then printf '%s\n' "$STUB_RUNNING"; fi
      exit "${STUB_INSPECT_RC:-0}" ;;
    *NetworkSettings.Networks*)
      printf '%s' "$STUB_NETWORK_IP"
      exit "${STUB_NETWORK_RC:-0}" ;;
    *NetworkSettings.IPAddress*)
      printf '%s' "$STUB_FLAT_IP"
      exit "${STUB_FLAT_RC:-0}" ;;
    *State.Status*)
      printf '%s' "$STUB_STATUS"
      exit "${STUB_STATUS_RC:-0}" ;;
  esac
  exit 1
fi
if [ "$1" = "run" ]; then
  printf '%s\n' "${STUB_RUN_ID:-stub-container-id}"
  exit "${STUB_RUN_RC:-0}"
fi
if [ "$1" = "logs" ]; then
  printf '%s\n' "$STUB_LOGS"
  exit 0
fi
if [ "$1" = "rm" ] || [ "$1" = "stop" ]; then
  if [ -n "$STUB_MISSING" ]; then
    echo "Error response from daemon: No such container: $3" >&2
    exit 1
  fi
  exit 0
fi
exit 1
`
	if err := os.WriteFile(path, []byte(script), 0o755); err != nil {
		t.Fatalf("writing stub runtime: %v", err)
	}

	t.Setenv("STUB_LOG", logPath)

	return path, logPath
}

func stubCalls(t *testing.T, logPath string) string {
	t.Helper()

	calls, err := os.ReadFile(logPath)
	if err != nil {
		if os.IsNotExist(err) {
			return ""
		}
		t.Fatalf("reading stub calls: %v", err)
	}

	return string(calls)
}

func testConfig(runtime string) *config.Config {
	return &config.Config{
		Container: config.ContainerConfig{
			Runtime:        runtime,
			Network:        "agentarea-mcp",
			MaxContainers:  4,
			StartupTimeout: 20 * time.Second,
		},
	}
}

func discardLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

// A container attached to a user-defined network has no flat IPAddress field,
// and current Docker releases fail the template instead of printing nothing. The
// address still has to come back, otherwise no MCP workload is ever reachable.
func TestContainerIPSurvivesAFailingFlatField(t *testing.T) {
	runtime, _ := stubRuntime(t)
	t.Setenv("STUB_NETWORK_IP", " 172.18.0.3 ")
	t.Setenv("STUB_FLAT_RC", "1")

	ip, err := NewHealthChecker(testConfig(runtime), discardLogger()).getContainerIP(context.Background(), "mcp-instance")
	if err != nil {
		t.Fatalf("getContainerIP() error = %v, want an address", err)
	}
	if ip != "172.18.0.3" {
		t.Fatalf("getContainerIP() = %q, want the network-scoped address", ip)
	}
}

// The reverse runtime shape: the networks map is empty and only the flat field
// carries the address. Both reads have to be attempted for either to work.
func TestContainerIPFallsBackToTheFlatField(t *testing.T) {
	runtime, _ := stubRuntime(t)
	t.Setenv("STUB_NETWORK_IP", "")
	t.Setenv("STUB_FLAT_IP", "10.0.0.5\n")

	ip, err := NewHealthChecker(testConfig(runtime), discardLogger()).getContainerIP(context.Background(), "mcp-instance")
	if err != nil {
		t.Fatalf("getContainerIP() error = %v, want an address", err)
	}
	if ip != "10.0.0.5" {
		t.Fatalf("getContainerIP() = %q, want the flat address", ip)
	}
}

func TestContainerIPReportsAnAddresslessContainer(t *testing.T) {
	runtime, _ := stubRuntime(t)
	t.Setenv("STUB_NETWORK_IP", "")
	t.Setenv("STUB_FLAT_IP", "")

	if _, err := NewHealthChecker(testConfig(runtime), discardLogger()).getContainerIP(context.Background(), "mcp-instance"); err == nil {
		t.Fatal("getContainerIP() error = nil, want a failure when no network reports an address")
	}
}

// A container that exits before it can serve is removed, and what it printed is
// kept. Nothing else records why it stopped: the caller gets an error and no
// handle, so an abandoned corpse would hold its name and disk for good, and the
// reason -- here a server told to speak HTTP that fell back to stdio -- would
// only be visible by reproducing the failure by hand on the host.
func TestCreateContainerRemovesAContainerThatExitedAndKeepsItsOutput(t *testing.T) {
	runtime, logPath := stubRuntime(t)
	t.Setenv("STUB_STATUS", "exited")
	t.Setenv("STUB_RUNNING", "false")
	t.Setenv("STUB_LOGS", "Terraform MCP Server running on stdio")

	var recorded bytes.Buffer
	manager := &Manager{
		config:     testConfig(runtime),
		logger:     slog.New(slog.NewTextHandler(&recorded, nil)),
		containers: map[string]*models.Container{},
	}

	if _, err := manager.CreateContainer(context.Background(), models.CreateContainerRequest{
		ServiceName: "inst-exits",
		Image:       "hashicorp/terraform-mcp-server:latest",
		Port:        8080,
	}); err == nil {
		t.Fatal("CreateContainer() error = nil, want the start failure reported")
	}

	if _, tracked := manager.containers["inst-exits"]; tracked {
		t.Fatal("a container that never served is still tracked as one that did")
	}

	calls := stubCalls(t, logPath)
	started := strings.Index(calls, "run -d")
	read := strings.Index(calls, "logs --tail")
	removed := strings.LastIndex(calls, "rm -f")
	if started < 0 {
		t.Fatalf("no container was started; runtime calls:\n%s", calls)
	}
	if read < started {
		t.Fatalf("the failed container was not read before removal; runtime calls:\n%s", calls)
	}
	if removed < read {
		t.Fatalf("the failed container was not removed; runtime calls:\n%s", calls)
	}
	if !strings.Contains(recorded.String(), "running on stdio") {
		t.Fatalf("the container output was not preserved; log:\n%s", recorded.String())
	}
}

// The ceiling a caller asked for is the one the runtime enforces. These values
// were accepted at the API, carried through the backend, and then dropped when the
// run was assembled, so every container silently ran on the host-wide default.
func TestRunArgsPreferTheCeilingTheWorkloadAskedFor(t *testing.T) {
	runtime, _ := stubRuntime(t)
	config := testConfig(runtime)
	config.Container.DefaultMemoryLimit = "512m"
	config.Container.DefaultCPULimit = "1.0"
	manager := &Manager{config: config, logger: discardLogger(), containers: map[string]*models.Container{}}

	asked := strings.Join(manager.buildContainerRunArgs(&models.Container{
		Name: "asked", Image: "vendor/mcp:1.0", MemoryLimit: "2g", CPULimit: "2.0",
	}), " ")
	if !strings.Contains(asked, "--memory 2g") || !strings.Contains(asked, "--cpus 2.0") {
		t.Fatalf("run args ignored the requested ceiling: %s", asked)
	}

	silent := strings.Join(manager.buildContainerRunArgs(&models.Container{
		Name: "silent", Image: "vendor/mcp:1.0",
	}), " ")
	if !strings.Contains(silent, "--memory 512m") || !strings.Contains(silent, "--cpus 1.0") {
		t.Fatalf("run args dropped the host default: %s", silent)
	}
}

// The ceiling in a spec is caller input: it arrives from the platform API and
// crosses into the data plane, which shares a host with agent sandboxes. A
// workload may size itself down; asking for more than the host allows is refused
// before the runtime is invoked, so one request cannot take the machine.
func TestCreateContainerRefusesACeilingAboveTheHostMaximum(t *testing.T) {
	runtime, logPath := stubRuntime(t)
	config := testConfig(runtime)
	config.Container.DefaultMemoryLimit = "512m"
	config.Container.DefaultCPULimit = "1.0"
	config.Container.MaxMemoryLimit = "512m"
	config.Container.MaxCPULimit = "1.0"
	manager := &Manager{config: config, logger: discardLogger(), containers: map[string]*models.Container{}}

	for name, req := range map[string]models.CreateContainerRequest{
		"memory": {ServiceName: "greedy-mem", Image: "vendor/mcp:1.0", Port: 8080, MemoryLimit: "100g"},
		"cpu":    {ServiceName: "greedy-cpu", Image: "vendor/mcp:1.0", Port: 8080, CPULimit: "64"},
		"junk":   {ServiceName: "junk-cpu", Image: "vendor/mcp:1.0", Port: 8080, CPULimit: "all-of-it"},
	} {
		if _, err := manager.CreateContainer(context.Background(), req); err == nil {
			t.Fatalf("%s: CreateContainer() error = nil, want the request refused", name)
		}
	}

	if calls := stubCalls(t, logPath); strings.Contains(calls, "run -d") {
		t.Fatalf("a refused request still reached the runtime:\n%s", calls)
	}

	// Under the ceiling the request is honoured, not quietly replaced.
	t.Setenv("STUB_STATUS", "running")
	accepted, err := manager.CreateContainer(context.Background(), models.CreateContainerRequest{
		ServiceName: "modest", Image: "vendor/mcp:1.0", Port: 8080, MemoryLimit: "256m", CPULimit: "0.5",
	})
	if err != nil {
		t.Fatalf("CreateContainer() with a smaller ceiling error = %v", err)
	}
	args := strings.Join(manager.buildContainerRunArgs(accepted), " ")
	if !strings.Contains(args, "--memory 256m") || !strings.Contains(args, "--cpus 0.5") {
		t.Fatalf("run args did not carry the requested ceiling: %s", args)
	}
}

// A dead container keeps its name, and the runtime refuses to reuse it. Without
// removing it first, every later attempt for that instance fails on the name
// rather than on whatever stopped the workload.
func TestStaleNamesakeIsRemoved(t *testing.T) {
	runtime, logPath := stubRuntime(t)
	t.Setenv("STUB_RUNNING", "false")

	manager := &Manager{config: testConfig(runtime), logger: discardLogger()}
	if err := manager.clearContainerName(context.Background(), "mcp-instance"); err != nil {
		t.Fatalf("clearContainerName() error = %v, want the corpse removed", err)
	}

	if calls := stubCalls(t, logPath); !strings.Contains(calls, "rm -f mcp-instance") {
		t.Fatalf("stale container was not removed; runtime calls:\n%s", calls)
	}
}

func TestRunningNamesakeIsReportedNotKilled(t *testing.T) {
	runtime, logPath := stubRuntime(t)
	t.Setenv("STUB_RUNNING", "true")

	manager := &Manager{config: testConfig(runtime), logger: discardLogger()}
	if err := manager.clearContainerName(context.Background(), "mcp-instance"); err == nil {
		t.Fatal("clearContainerName() error = nil, want a running namesake reported")
	}

	if calls := stubCalls(t, logPath); strings.Contains(calls, "rm -f") {
		t.Fatalf("a running container was removed; runtime calls:\n%s", calls)
	}
}

func TestAbsentNameNeedsNoWork(t *testing.T) {
	runtime, logPath := stubRuntime(t)
	t.Setenv("STUB_INSPECT_RC", "1")

	manager := &Manager{config: testConfig(runtime), logger: discardLogger()}
	if err := manager.clearContainerName(context.Background(), "mcp-instance"); err != nil {
		t.Fatalf("clearContainerName() error = %v, want a free name accepted", err)
	}

	if calls := stubCalls(t, logPath); strings.Contains(calls, "rm -f") {
		t.Fatalf("removal ran for a name nothing holds; runtime calls:\n%s", calls)
	}
}

// Retirement has to survive a container that is already gone: the host reaps
// one, a runtime restart loses it, an operator removes it by hand. Reporting
// that as a failure left the control-plane record permanently undeletable.
func TestRetiringAnAlreadyRemovedContainerSucceeds(t *testing.T) {
	runtime, logPath := stubRuntime(t)
	t.Setenv("STUB_MISSING", "1")

	manager := &Manager{
		config:     testConfig(runtime),
		logger:     discardLogger(),
		containers: map[string]*models.Container{"weather": {ID: "container-1", Name: "mcp-weather"}},
	}

	if err := manager.DeleteContainer(context.Background(), "weather"); err != nil {
		t.Fatalf("DeleteContainer() error = %v, want a container that is already gone accepted", err)
	}
	if _, still := manager.containers["weather"]; still {
		t.Fatal("the record survived retirement, so the instance can never be recreated")
	}
	if calls := stubCalls(t, logPath); !strings.Contains(calls, "rm -f container-1") {
		t.Fatalf("removal was not attempted; runtime calls:\n%s", calls)
	}
}

// A refusal has to name a cause the caller can act on, while the runtime\x27s own
// text -- which can carry host paths and registry hints -- stays in the log.
func TestRuntimeRefusalNamesTheCauseWithoutEchoingTheRuntime(t *testing.T) {
	denied := []byte("Unable to find image locally\ndocker: Error response from daemon: pull access denied for reg.example.com/team/app, repository does not exist or may require \x27docker login\x27\n")
	got := runtimeRefusal(denied)
	if !strings.Contains(got, "no credentials") {
		t.Fatalf("runtimeRefusal() = %q, want the missing-credential cause", got)
	}
	if strings.Contains(got, "reg.example.com") || strings.Contains(got, "team/app") {
		t.Fatalf("runtimeRefusal() = %q, want no runtime text echoed to callers", got)
	}
	if got := runtimeRefusal([]byte("docker: Error response from daemon: Conflict. The container name \"/mcp-x\" is already in use by container \"abc\".")); !strings.Contains(got, "name") {
		t.Fatalf("runtimeRefusal() = %q, want the name conflict named", got)
	}
	if got := runtimeRefusal(nil); got != "the runtime failed without output" {
		t.Fatalf("runtimeRefusal(nil) = %q, want a stated absence", got)
	}
}
