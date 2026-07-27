package config

import (
	"fmt"
	"sort"

	"github.com/agentarea/mcp-manager/internal/models"
)

// Isolation tiers. The tier names what we assume about the code, so the call
// site declares trust rather than remembering a flag list.
const (
	// IsolationTrusted is for images we build and ship ourselves.
	IsolationTrusted = "trusted"
	// IsolationStandard is for third-party MCP servers from the catalog:
	// confined, but on the host's default runtime.
	IsolationStandard = "standard"
	// IsolationUntrusted is for code a user supplied — custom MCP servers and
	// agent-authored programs. Adds a syscall-interposing runtime on top.
	IsolationUntrusted = "untrusted"
)

// UntrustedRuntime is the runtime class the untrusted tier asks for. gVisor's
// runsc needs no KVM (systrap), so it is the portable choice; deployments with
// /dev/kvm can point this at a microVM runtime instead.
const UntrustedRuntime = "runsc"

// isolationProfiles maps a tier to its resolved settings. Everything except the
// trusted tier drops all capabilities and blocks privilege escalation — those
// are cheap and break almost nothing, so the tiers differ mainly in runtime.
var isolationProfiles = map[string]models.Isolation{
	IsolationTrusted: {
		Profile:         IsolationTrusted,
		NoNewPrivileges: true,
	},
	IsolationStandard: {
		Profile:          IsolationStandard,
		DropCapabilities: []string{"ALL"},
		NoNewPrivileges:  true,
		PidsLimit:        512,
	},
	IsolationUntrusted: {
		Profile:          IsolationUntrusted,
		Runtime:          UntrustedRuntime,
		DropCapabilities: []string{"ALL"},
		NoNewPrivileges:  true,
		PidsLimit:        256,
	},
}

// ResolveIsolation returns the profile for a tier.
//
// An unknown tier is an error, never a silent fallback to a weaker one: a typo
// in a deployment value must stop the workload, not quietly run third-party
// code unconfined.
func ResolveIsolation(tier string) (models.Isolation, error) {
	profile, ok := isolationProfiles[tier]
	if !ok {
		return models.Isolation{}, fmt.Errorf(
			"unknown isolation tier %q (known: %v)", tier, IsolationTiers(),
		)
	}
	// Copy the slice so a caller appending to it cannot mutate the table.
	profile.DropCapabilities = append([]string(nil), profile.DropCapabilities...)
	return profile, nil
}

// IsolationTiers lists the known tiers in a stable order, for error messages
// and operator-facing output.
func IsolationTiers() []string {
	tiers := make([]string, 0, len(isolationProfiles))
	for name := range isolationProfiles {
		tiers = append(tiers, name)
	}
	sort.Strings(tiers)
	return tiers
}
