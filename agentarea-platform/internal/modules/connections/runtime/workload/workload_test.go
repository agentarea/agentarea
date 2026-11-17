package workload

import (
	"slices"
	"testing"
)

func TestValidateImageReferenceAcceptsRealReferences(t *testing.T) {
	for _, image := range []string{
		"alpine", "alpine:3.20", "mcp/fetch", "ghcr.io/github/github-mcp-server:latest",
		"registry.example.com:5000/team/server:v1.2.3", "localhost:5000/server",
		"python@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
		"agentarea/mcp-base:dev",
	} {
		if err := ValidateImageReference(image); err != nil {
			t.Errorf("ValidateImageReference(%q) = %v", image, err)
		}
	}
}

// The image sits in the flag position of a runtime argv; a value read as a
// flag hands the container the host.
func TestValidateImageReferenceRefusesRuntimeFlags(t *testing.T) {
	for _, image := range []string{
		"--volume=/var/run/docker.sock:/var/run/docker.sock", "--privileged", "-v/:/host",
		"alpine --privileged", "alpine\n--privileged", "",
	} {
		if err := ValidateImageReference(image); err == nil {
			t.Errorf("ValidateImageReference(%q) = nil", image)
		}
	}
}

func TestSpecIsolationUsesTheDefaultTierWhenTheSpecIsSilent(t *testing.T) {
	iso, err := SpecIsolation(Spec{}, IsolationUntrusted)
	if err != nil || iso.Profile != IsolationUntrusted {
		t.Fatalf("iso %+v err %v", iso, err)
	}
}

func TestSpecIsolationPrefersTheSpecTier(t *testing.T) {
	iso, err := SpecIsolation(Spec{IsolationTier: IsolationUntrusted}, IsolationStandard)
	if err != nil || iso.Runtime != UntrustedRuntime {
		t.Fatalf("iso %+v err %v", iso, err)
	}
}

// An unknown tier never degrades to a weaker profile.
func TestSpecIsolationRejectsAnUnknownTier(t *testing.T) {
	if _, err := SpecIsolation(Spec{IsolationTier: "nope"}, IsolationStandard); err == nil {
		t.Fatal("an unknown tier was accepted")
	}
}

func TestSpecRuntimeClassCannotReplaceTheTierRuntime(t *testing.T) {
	if _, err := SpecIsolation(Spec{IsolationTier: IsolationUntrusted, RuntimeClass: "runc"}, IsolationStandard); err == nil {
		t.Fatal("a spec runtime class replaced the untrusted tier's runtime")
	}
}

func TestWritablePathsImplyAReadOnlyRoot(t *testing.T) {
	iso, err := SpecIsolation(Spec{WritablePaths: []string{"/tmp"}}, IsolationStandard)
	if err != nil || !iso.ReadOnlyRootFilesystem {
		t.Fatalf("iso %+v err %v", iso, err)
	}
}

// A cluster-wide sandbox runtime is never removable by a workload.
func TestTightenRuntimeClassOperatorWinsThenTierThenSpec(t *testing.T) {
	for _, c := range []struct{ configured, tier, spec, want string }{
		{"kata-qemu", "runsc", "runc", "kata-qemu"},
		{"", "runsc", "runc", "runsc"},
		{"", "", "runc", "runc"},
		{"", "", "", ""},
	} {
		if got := TightenRuntimeClass(c.configured, Isolation{Runtime: c.tier}, c.spec); got != c.want {
			t.Errorf("%+v: got %q", c, got)
		}
	}
}

func TestTightenDropCapabilitiesIsAUnionThatLeavesTheConfiguredSlice(t *testing.T) {
	configured := []string{"NET_RAW"}
	got := TightenDropCapabilities(configured, Isolation{DropCapabilities: []string{"ALL", "NET_RAW"}})
	if !slices.Contains(got, "ALL") || !slices.Contains(got, "NET_RAW") || len(got) != 2 {
		t.Fatalf("got %v", got)
	}
	if len(configured) != 1 {
		t.Fatalf("configured slice mutated: %v", configured)
	}
}
