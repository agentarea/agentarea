package container

import (
	"slices"
	"strings"
	"testing"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/models"
)

// hasFlagPair reports whether args contains `flag value` adjacently.
func hasFlagPair(args []string, flag, value string) bool {
	for i := 0; i < len(args)-1; i++ {
		if args[i] == flag && args[i+1] == value {
			return true
		}
	}
	return false
}

func TestIsolationRunArgsRendersEachSetting(t *testing.T) {
	args := isolationRunArgs(models.Isolation{
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
	// A zero Isolation must not silently invent confinement — callers resolve a
	// named tier, and rendering defaults here would hide a missing resolution.
	if args := isolationRunArgs(models.Isolation{}); len(args) != 0 {
		t.Errorf("expected no flags for zero isolation, got %v", args)
	}
}

func TestIsolationRunArgsOmitsTmpfsWithoutReadOnlyRoot(t *testing.T) {
	// tmpfs mounts exist to make a read-only rootfs usable; without one they
	// would silently shadow real image directories.
	args := isolationRunArgs(models.Isolation{WritablePaths: []string{"/tmp"}})
	if slices.Contains(args, "--tmpfs") {
		t.Errorf("tmpfs applied without read-only rootfs: %v", args)
	}
}

func TestResolvedTiersConfineThirdPartyCode(t *testing.T) {
	// standard and untrusted both run third-party code: dropping capabilities
	// and blocking privilege escalation is the floor for both.
	for _, tier := range []string{config.IsolationStandard, config.IsolationUntrusted} {
		iso, err := config.ResolveIsolation(tier)
		if err != nil {
			t.Fatalf("resolving %s: %v", tier, err)
		}
		args := isolationRunArgs(iso)
		if !hasFlagPair(args, "--cap-drop", "ALL") {
			t.Errorf("%s does not drop capabilities: %v", tier, args)
		}
		if !hasFlagPair(args, "--security-opt", "no-new-privileges") {
			t.Errorf("%s allows privilege escalation: %v", tier, args)
		}
	}
}

func TestUntrustedTierAsksForASyscallInterposingRuntime(t *testing.T) {
	iso, err := config.ResolveIsolation(config.IsolationUntrusted)
	if err != nil {
		t.Fatalf("resolving untrusted: %v", err)
	}
	if iso.Runtime != config.UntrustedRuntime {
		t.Errorf("untrusted tier runtime = %q, want %q", iso.Runtime, config.UntrustedRuntime)
	}
	if !iso.RequiresRuntime() {
		t.Error("untrusted tier must report that it requires a runtime, so callers fail closed")
	}
}

func TestStandardTierDoesNotRequireASpecialRuntime(t *testing.T) {
	// standard must stay deployable on a stock daemon, otherwise every catalog
	// MCP server would refuse to start on hosts without gVisor.
	iso, err := config.ResolveIsolation(config.IsolationStandard)
	if err != nil {
		t.Fatalf("resolving standard: %v", err)
	}
	if iso.RequiresRuntime() {
		t.Errorf("standard tier requires runtime %q; it must run on a stock daemon", iso.Runtime)
	}
}

func TestResolveIsolationRejectsUnknownTier(t *testing.T) {
	// A typo in a deployment value must stop the workload, not quietly run
	// third-party code unconfined.
	if _, err := config.ResolveIsolation("untrused"); err == nil {
		t.Fatal("expected an error for an unknown tier, got nil")
	}
}

func TestResolveIsolationDoesNotAliasTheProfileTable(t *testing.T) {
	first, err := config.ResolveIsolation(config.IsolationUntrusted)
	if err != nil {
		t.Fatalf("resolving: %v", err)
	}
	first.DropCapabilities = append(first.DropCapabilities, "MUTATED")

	second, err := config.ResolveIsolation(config.IsolationUntrusted)
	if err != nil {
		t.Fatalf("resolving: %v", err)
	}
	if slices.Contains(second.DropCapabilities, "MUTATED") {
		t.Error("mutating a resolved profile leaked into the shared table")
	}
}

func TestErrRuntimeUnavailableNamesWhatWasRefused(t *testing.T) {
	err := &ErrRuntimeUnavailable{Runtime: "runsc", Available: []string{"runc"}}
	msg := err.Error()
	if !strings.Contains(msg, "runsc") || !strings.Contains(msg, "runc") {
		t.Errorf("error should name requested and available runtimes: %q", msg)
	}
}
