package workload

import (
	"fmt"
	"slices"
	"sort"
)

// Isolation tiers name what is assumed about the code a workload runs.
const (
	// IsolationTrusted is for images the platform builds itself.
	IsolationTrusted = "trusted"
	// IsolationStandard is for third-party catalog servers: confined, default runtime.
	IsolationStandard = "standard"
	// IsolationUntrusted is for user-supplied code: adds a syscall-interposing runtime.
	IsolationUntrusted = "untrusted"
)

// UntrustedRuntime is the runtime class of the untrusted tier (gVisor).
const UntrustedRuntime = "runsc"

// Isolation is the resolved confinement of one workload. The zero value means
// nothing was resolved, never that confinement is not needed.
type Isolation struct {
	Profile                string
	Runtime                string
	DropCapabilities       []string
	NoNewPrivileges        bool
	ReadOnlyRootFilesystem bool
	WritablePaths          []string
	PidsLimit              int
	User                   string
}

func profiles() map[string]Isolation {
	return map[string]Isolation{
		IsolationTrusted:   {Profile: IsolationTrusted, NoNewPrivileges: true},
		IsolationStandard:  {Profile: IsolationStandard, DropCapabilities: []string{"ALL"}, NoNewPrivileges: true, PidsLimit: 512},
		IsolationUntrusted: {Profile: IsolationUntrusted, Runtime: UntrustedRuntime, DropCapabilities: []string{"ALL"}, NoNewPrivileges: true, PidsLimit: 256},
	}
}

// IsolationTiers lists the known tiers in a stable order.
func IsolationTiers() []string {
	p := profiles()
	out := make([]string, 0, len(p))
	for name := range p {
		out = append(out, name)
	}
	sort.Strings(out)
	return out
}

// ResolveIsolation returns a tier's profile. An unknown tier is an error,
// never a weaker tier.
func ResolveIsolation(tier string) (Isolation, error) {
	p, ok := profiles()[tier]
	if !ok {
		return Isolation{}, fmt.Errorf("unknown isolation tier %q (known: %v)", tier, IsolationTiers())
	}
	return p, nil
}

// SpecIsolation resolves the spec's tier, defaultTier when it names none. A
// spec runtime class may not replace the tier's own runtime; writable paths
// make the root filesystem read-only.
func SpecIsolation(spec Spec, defaultTier string) (Isolation, error) {
	tier := spec.IsolationTier
	if tier == "" {
		tier = defaultTier
	}
	iso, err := ResolveIsolation(tier)
	if err != nil {
		return Isolation{}, err
	}
	if spec.RuntimeClass != "" {
		if iso.Runtime != "" && iso.Runtime != spec.RuntimeClass {
			return Isolation{}, fmt.Errorf("instance runtime class %q may not replace the %q tier's %q", spec.RuntimeClass, tier, iso.Runtime)
		}
		iso.Runtime = spec.RuntimeClass
	}
	if len(spec.WritablePaths) > 0 {
		iso.ReadOnlyRootFilesystem = true
		iso.WritablePaths = slices.Clone(spec.WritablePaths)
	}
	return iso, nil
}

// TightenDropCapabilities adds the isolation's dropped capabilities to the
// configured ones: configuration may drop more, never fewer.
func TightenDropCapabilities(configured []string, iso Isolation) []string {
	merged := slices.Clone(configured)
	for _, c := range iso.DropCapabilities {
		if !slices.Contains(merged, c) {
			merged = append(merged, c)
		}
	}
	return merged
}

// TightenRuntimeClass picks the configured runtime class, else the tier's,
// else the spec's.
func TightenRuntimeClass(configured string, iso Isolation, specRuntimeClass string) string {
	switch {
	case configured != "":
		return configured
	case iso.Runtime != "":
		return iso.Runtime
	default:
		return specRuntimeClass
	}
}
