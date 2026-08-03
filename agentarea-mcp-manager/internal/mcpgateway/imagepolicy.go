package mcpgateway

import (
	"fmt"
	"os"
	"strings"
)

// ImagePolicy is the admission gate for what a container-backed MCP instance is
// allowed to run.
//
// It exists because confinement and admission are different questions. The
// isolation tier decides how tightly a workload is boxed; this decides whether
// the workload gets to exist at all. On a cluster whose nodes offer only the
// default runtime there is no kernel boundary to fall back on, so the set of
// runnable code has to be closed by name.
//
// Both surfaces are covered deliberately. Gating images while leaving
// command-type instances open would be no gate: `npx <anything>` reaches the
// same place by a different door.
type ImagePolicy struct {
	repositories map[string]struct{}
	packages     map[string]struct{}
}

// LoadImagePolicyFromEnv reads the declared admission lists. Both variables are
// required — an absent list is an operator who has not decided yet, and
// answering that with "allow everything" is the failure this type exists to
// prevent. A declared-but-empty list disables that surface.
func LoadImagePolicyFromEnv() (ImagePolicy, error) {
	repositories, err := requiredStringSetEnv("MCP_ALLOWED_IMAGE_REPOSITORIES")
	if err != nil {
		return ImagePolicy{}, err
	}
	packages, err := requiredStringSetEnv("MCP_ALLOWED_COMMAND_PACKAGES")
	if err != nil {
		return ImagePolicy{}, err
	}
	if len(repositories) == 0 && len(packages) == 0 {
		return ImagePolicy{}, fmt.Errorf(
			"MCP_ALLOWED_IMAGE_REPOSITORIES and MCP_ALLOWED_COMMAND_PACKAGES are both empty; no MCP instance could ever start",
		)
	}
	return ImagePolicy{repositories: repositories, packages: packages}, nil
}

// requiredStringSetEnv reads a comma-separated list. Presence and emptiness are
// different answers, so LookupEnv rather than Getenv: "" is a declared empty
// list, absent is an undeclared one.
func requiredStringSetEnv(name string) (map[string]struct{}, error) {
	raw, declared := os.LookupEnv(name)
	if !declared {
		return nil, fmt.Errorf("%s is required (declare it empty to disable this instance type)", name)
	}
	set := make(map[string]struct{})
	for _, entry := range strings.Split(raw, ",") {
		trimmed := strings.TrimSpace(entry)
		if trimmed == "" {
			continue
		}
		set[trimmed] = struct{}{}
	}
	return set, nil
}

// AuthorizeImage admits one container image by repository. The tag or digest is
// not part of the decision: pinning is a separate guarantee, and pretending a
// repository allowlist provides it would overstate what was checked.
func (p ImagePolicy) AuthorizeImage(image string) error {
	repository, ok := ociRepository(image)
	if !ok {
		return fmt.Errorf("MCP instance image %q is not a usable OCI reference", image)
	}
	if _, admitted := p.repositories[repository]; !admitted {
		return fmt.Errorf(
			"MCP instance image repository %q is not in MCP_ALLOWED_IMAGE_REPOSITORIES",
			repository,
		)
	}
	return nil
}

// AuthorizeCommand admits one stdio command. The executable is matched whole:
// a command-type instance names a package to fetch and run, so the package name
// is the thing an operator can meaningfully vouch for.
func (p ImagePolicy) AuthorizeCommand(command string) error {
	trimmed := strings.TrimSpace(command)
	if trimmed == "" {
		return fmt.Errorf("MCP command instance declares no command")
	}
	if _, admitted := p.packages[trimmed]; !admitted {
		return fmt.Errorf(
			"MCP instance command %q is not in MCP_ALLOWED_COMMAND_PACKAGES",
			trimmed,
		)
	}
	return nil
}

// ociRepository strips the tag or digest, leaving the registry/name part that
// the allowlist is expressed in.
func ociRepository(image string) (string, bool) {
	trimmed := strings.TrimSpace(image)
	if trimmed == "" {
		return "", false
	}
	if repository, _, found := strings.Cut(trimmed, "@"); found {
		trimmed = repository
	}
	// A colon before the last slash belongs to a registry port, not a tag.
	if lastColon := strings.LastIndexByte(trimmed, ':'); lastColon > strings.LastIndexByte(trimmed, '/') {
		trimmed = trimmed[:lastColon]
	}
	if trimmed == "" {
		return "", false
	}
	return trimmed, true
}
