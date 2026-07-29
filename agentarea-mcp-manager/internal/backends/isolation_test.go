package backends

import (
	"slices"
	"testing"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/models"
)

func TestResolveSpecIsolationUsesDefaultTierWhenSpecIsSilent(t *testing.T) {
	iso, err := resolveSpecIsolation(&InstanceSpec{}, config.IsolationUntrusted)
	if err != nil {
		t.Fatalf("resolving: %v", err)
	}
	if iso.Profile != config.IsolationUntrusted {
		t.Errorf("profile = %q, want %q", iso.Profile, config.IsolationUntrusted)
	}
}

func TestResolveSpecIsolationPrefersTheSpecTier(t *testing.T) {
	iso, err := resolveSpecIsolation(
		&InstanceSpec{IsolationTier: config.IsolationUntrusted},
		config.IsolationStandard,
	)
	if err != nil {
		t.Fatalf("resolving: %v", err)
	}
	if iso.Runtime != config.UntrustedRuntime {
		t.Errorf("runtime = %q, want %q", iso.Runtime, config.UntrustedRuntime)
	}
}

func TestResolveSpecIsolationRejectsUnknownTier(t *testing.T) {
	// Fail closed: an unrecognised tier must not silently degrade to a weaker
	// profile, or a typo in a deployment value would unconfine third-party code.
	if _, err := resolveSpecIsolation(&InstanceSpec{IsolationTier: "nope"}, config.IsolationStandard); err == nil {
		t.Fatal("expected an error for an unknown tier")
	}
}

func TestResolveSpecIsolationWritablePathsImplyReadOnlyRoot(t *testing.T) {
	iso, err := resolveSpecIsolation(
		&InstanceSpec{WritablePaths: []string{"/tmp"}},
		config.IsolationStandard,
	)
	if err != nil {
		t.Fatalf("resolving: %v", err)
	}
	if !iso.ReadOnlyRootFilesystem {
		t.Error("declaring writable paths must turn on the read-only root they carve out of")
	}
}

func TestTightenRuntimeClassOperatorWins(t *testing.T) {
	// A cluster-wide sandbox runtime must not be removable by a workload, or
	// the per-workload knob becomes a downgrade path.
	got := tightenRuntimeClass("kata-qemu", models.Isolation{Runtime: "runsc"}, "runc")
	if got != "kata-qemu" {
		t.Errorf("got %q, want the operator's kata-qemu", got)
	}
}

func TestTightenRuntimeClassFallsBackToTierThenSpec(t *testing.T) {
	if got := tightenRuntimeClass("", models.Isolation{Runtime: "runsc"}, "runc"); got != "runsc" {
		t.Errorf("tier runtime should outrank the spec field, got %q", got)
	}
	if got := tightenRuntimeClass("", models.Isolation{}, "runc"); got != "runc" {
		t.Errorf("spec field should apply when nothing else does, got %q", got)
	}
	if got := tightenRuntimeClass("", models.Isolation{}, ""); got != "" {
		t.Errorf("expected empty (daemon default), got %q", got)
	}
}

func TestTightenDropCapabilitiesIsAUnion(t *testing.T) {
	got := tightenDropCapabilities([]string{"NET_RAW"}, models.Isolation{DropCapabilities: []string{"ALL", "NET_RAW"}})

	if !slices.Contains(got, "NET_RAW") || !slices.Contains(got, "ALL") {
		t.Errorf("union should keep both operator and tier drops, got %v", got)
	}
	if len(got) != 2 {
		t.Errorf("expected no duplicates, got %v", got)
	}
}

func TestTightenDropCapabilitiesDoesNotMutateTheConfiguredSlice(t *testing.T) {
	configured := []string{"NET_RAW"}
	tightenDropCapabilities(configured, models.Isolation{DropCapabilities: []string{"ALL"}})

	if len(configured) != 1 {
		t.Errorf("operator config was mutated: %v", configured)
	}
}
