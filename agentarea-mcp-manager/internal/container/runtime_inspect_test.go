package container

import (
	"context"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"testing"

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
  esac
  exit 1
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
			Runtime: runtime,
			Network: "agentarea-mcp",
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
