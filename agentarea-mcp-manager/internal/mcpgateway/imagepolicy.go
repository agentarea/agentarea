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

// AuthorizeImage admits one container image by repository, together with any
// command the instance overrides the image's own with. The tag or digest is not
// part of the decision: pinning is a separate guarantee, and pretending a
// repository allowlist provides it would overstate what was checked.
//
// The override is judged because it reaches the pod as container args, so an
// image vouched for as published is not the program that runs once the caller
// chooses its argv. A repository-only entry therefore admits the image only as
// the image ships it; to permit an override the operator declares the whole
// invocation, "<repository> <arg>...", exactly as they do for stdio commands.
func (p ImagePolicy) AuthorizeImage(image string, command []string) error {
	repository, ok := ociRepository(image)
	if !ok {
		return fmt.Errorf("MCP instance image %q is not a usable OCI reference", image)
	}
	invocation := repository
	if len(command) > 0 {
		invocation = strings.Join(append([]string{repository}, command...), " ")
	}
	if _, admitted := p.repositories[invocation]; !admitted {
		return fmt.Errorf(
			"MCP instance image invocation %q is not in MCP_ALLOWED_IMAGE_REPOSITORIES",
			invocation,
		)
	}
	return nil
}

// launcherEnvironmentDenied names the environment a package launcher reads to
// decide where code comes from, by exact name or by namespace prefix. Compared
// case-insensitively because npm reads npm_config_* in either case.
//
// Three ways to move a launcher off its registry, all closed here: name another
// index outright (npm_config_registry, UV_INDEX_URL, PIP_INDEX_URL), route the
// fetch through a host you control (the proxy variables), or keep the address
// and break the proof of who answered (NODE_TLS_REJECT_UNAUTHORIZED and the CA
// bundle overrides). Whole namespaces rather than known keys, so a launcher
// adding a setting does not quietly open the door again.
var launcherEnvironmentDenied = struct {
	prefixes []string
	exact    []string
}{
	prefixes: []string{"NPM_CONFIG_", "UV_", "PIP_"},
	exact: []string{
		"PATH", "HOME",
		"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP",
		"NODE_OPTIONS", "NODE_PATH", "NODE_EXTRA_CA_CERTS", "NODE_TLS_REJECT_UNAUTHORIZED",
		"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
		"SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
		"GIT_SSL_NO_VERIFY", "GIT_SSL_CAINFO",
	},
}

// AuthorizeLauncherEnvironment refuses instance environment that would move a
// launcher off the registry its allowlist entry was written against.
//
// An entry like "npx -y @scope/server" is a statement about a specific package
// from a specific registry. npm_config_registry, UV_INDEX_URL and PIP_INDEX_URL
// each rewrite the second half of that sentence while leaving the first half
// matching, so admitting them would hand back the whole npm and PyPI namespace
// the invocation check exists to close. Where code is fetched from is the
// operator's decision, so it is not one an instance gets to carry.
func (p ImagePolicy) AuthorizeLauncherEnvironment(environment map[string]string) error {
	for name := range environment {
		upper := strings.ToUpper(strings.TrimSpace(name))
		for _, exact := range launcherEnvironmentDenied.exact {
			if upper == exact {
				return fmt.Errorf("MCP command instance may not set %q: it redirects package resolution", name)
			}
		}
		for _, prefix := range launcherEnvironmentDenied.prefixes {
			if strings.HasPrefix(upper, prefix) {
				return fmt.Errorf("MCP command instance may not set %q: it redirects package resolution", name)
			}
		}
	}
	return nil
}

// AuthorizeCommand admits one stdio invocation, matched whole: the executable
// and every argument together.
//
// The executable alone would not be a gate. `npx` and `uvx` fetch and run
// whatever package they are pointed at, so admitting the interpreter admits the
// entire npm and PyPI namespaces — the exact door this type exists to close.
// The package lives in the arguments, and so does anything that redirects which
// package is fetched (`--package`, `--from`, a version pin), which is why the
// decision is made on the whole invocation rather than on a name parsed out of
// it. Instance arguments come from the catalog's server spec, not from user
// input, so an exact invocation is something an operator can actually vouch for.
func (p ImagePolicy) AuthorizeCommand(command string, args []string) error {
	if strings.TrimSpace(command) == "" {
		return fmt.Errorf("MCP command instance declares no command")
	}
	invocation := strings.Join(append([]string{strings.TrimSpace(command)}, args...), " ")
	if _, admitted := p.packages[invocation]; !admitted {
		return fmt.Errorf(
			"MCP instance command %q is not in MCP_ALLOWED_COMMAND_PACKAGES",
			invocation,
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
