package packageimage

import (
	"fmt"
	"regexp"
	"strings"
)

// Ecosystem identifies the package index and install tool used by a command.
type Ecosystem string

const (
	EcosystemNPM  Ecosystem = "npm"
	EcosystemPyPI Ecosystem = "pypi"
)

// Invocation is the validated package invocation carried by a command
// connection. Version is empty when the invocation asks for the latest release.
type Invocation struct {
	Ecosystem  Ecosystem
	Package    string
	Version    string
	Executable string
	Args       []string
}

var (
	npmExactVersion  = regexp.MustCompile(`^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$`)
	pypiExactVersion = regexp.MustCompile(`^[0-9]+(?:\.[0-9]+)*(?:[A-Za-z][0-9]*)?(?:[-_.][A-Za-z0-9]+)*$`)
)

// ParseInvocation validates the command argv accepted by Contract 2.
func ParseInvocation(command []string) (Invocation, error) {
	if len(command) == 0 {
		return Invocation{}, fmt.Errorf("command invocation is empty")
	}
	switch command[0] {
	case "npx":
		return parseNpxInvocation(command)
	case "uvx":
		return parseUvxInvocation(command)
	default:
		return Invocation{}, fmt.Errorf("unsupported package command %q", command[0])
	}
}

func parseNpxInvocation(command []string) (Invocation, error) {
	invocation := Invocation{Ecosystem: EcosystemNPM}
	packageSet, packageFromFlag := false, false
	for index := 1; index < len(command); index++ {
		token := command[index]
		if packageSet {
			appendInvocationToken(&invocation, token, packageFromFlag)
			continue
		}
		switch token {
		case "-y", "--yes", "-q", "--quiet":
			continue
		case "-p", "--package":
			name, version, next, err := parsePackageFlag(command, index, EcosystemNPM)
			if err != nil {
				return Invocation{}, err
			}
			invocation.Package, invocation.Version = name, version
			index, packageSet, packageFromFlag = next, true, true
		case "--from":
			return Invocation{}, fmt.Errorf("unsupported npx flag %q", token)
		default:
			if strings.HasPrefix(token, "--package=") || strings.HasPrefix(token, "--from=") {
				name, version, err := parseEqualsPackageFlag(token, EcosystemNPM, "--package")
				if err != nil {
					return Invocation{}, err
				}
				invocation.Package, invocation.Version = name, version
				packageSet, packageFromFlag = true, true
				continue
			}
			if strings.HasPrefix(token, "-") {
				return Invocation{}, fmt.Errorf("unsupported npx flag %q", token)
			}
			name, version, err := parsePackageSpec(EcosystemNPM, token)
			if err != nil {
				return Invocation{}, err
			}
			invocation.Package, invocation.Version, packageSet = name, version, true
		}
	}
	if !packageSet {
		return Invocation{}, fmt.Errorf("package spec is required")
	}
	return invocation, nil
}

func parseUvxInvocation(command []string) (Invocation, error) {
	invocation := Invocation{Ecosystem: EcosystemPyPI}
	packageSet, packageFromFlag := false, false
	for index := 1; index < len(command); index++ {
		token := command[index]
		if packageSet {
			appendInvocationToken(&invocation, token, packageFromFlag)
			continue
		}
		switch token {
		case "-q", "--quiet":
			continue
		case "-p":
			return Invocation{}, fmt.Errorf("unsupported uvx flag %q", token)
		case "--package", "--from":
			name, version, next, err := parsePackageFlag(command, index, EcosystemPyPI)
			if err != nil {
				return Invocation{}, err
			}
			invocation.Package, invocation.Version = name, version
			index, packageSet, packageFromFlag = next, true, true
		default:
			if strings.HasPrefix(token, "--package=") || strings.HasPrefix(token, "--from=") {
				name, version, err := parseEqualsPackageFlag(token, EcosystemPyPI, "--from")
				if err != nil {
					return Invocation{}, err
				}
				invocation.Package, invocation.Version = name, version
				packageSet, packageFromFlag = true, true
				continue
			}
			if strings.HasPrefix(token, "-") {
				return Invocation{}, fmt.Errorf("unsupported uvx flag %q", token)
			}
			name, version, err := parsePackageSpec(EcosystemPyPI, token)
			if err != nil {
				return Invocation{}, err
			}
			invocation.Package, invocation.Version, packageSet = name, version, true
		}
	}
	if !packageSet {
		return Invocation{}, fmt.Errorf("package spec is required")
	}
	return invocation, nil
}

func parsePackageFlag(command []string, index int, ecosystem Ecosystem) (string, string, int, error) {
	flag := command[index]
	if index+1 >= len(command) {
		return "", "", index, fmt.Errorf("flag %q requires a package spec", flag)
	}
	spec := command[index+1]
	if strings.HasPrefix(spec, "-") {
		return "", "", index, fmt.Errorf("flag %q requires a package spec", flag)
	}
	name, version, err := parsePackageSpec(ecosystem, spec)
	return name, version, index + 1, err
}

func parseEqualsPackageFlag(token string, ecosystem Ecosystem, expected string) (string, string, error) {
	flag, spec, ok := strings.Cut(token, "=")
	if !ok || spec == "" {
		return "", "", fmt.Errorf("flag %q requires a package spec", flag)
	}
	if flag != expected {
		return "", "", fmt.Errorf("unsupported %s flag %q", ecosystem, flag)
	}
	return parsePackageSpec(ecosystem, spec)
}

func appendInvocationToken(invocation *Invocation, token string, packageFromFlag bool) {
	if packageFromFlag && invocation.Executable == "" && !strings.HasPrefix(token, "-") {
		invocation.Executable = token
		return
	}
	invocation.Args = append(invocation.Args, token)
}

func parsePackageSpec(ecosystem Ecosystem, spec string) (string, string, error) {
	if strings.TrimSpace(spec) != spec || spec == "" {
		return "", "", fmt.Errorf("invalid %s package spec %q", ecosystem, spec)
	}
	if strings.ContainsAny(spec, "[];:#/\\") {
		if ecosystem == EcosystemNPM && strings.HasPrefix(spec, "@") && strings.Count(spec, "/") == 1 {
			// A scoped npm package has exactly one slash and is handled below.
		} else {
			return "", "", fmt.Errorf("unsupported %s package spec %q", ecosystem, spec)
		}
	}
	if ecosystem == EcosystemNPM {
		return parseNPMspec(spec)
	}
	return parsePyPIspec(spec)
}

func parseNPMspec(spec string) (string, string, error) {
	name := spec
	version := ""
	if strings.HasPrefix(spec, "@") {
		slash := strings.IndexByte(spec, '/')
		if slash <= 1 || slash == len(spec)-1 || strings.Count(spec, "/") != 1 {
			return "", "", fmt.Errorf("invalid npm package spec %q", spec)
		}
		if at := strings.IndexByte(spec[slash+1:], '@'); at >= 0 {
			at += slash + 1
			name, version = spec[:at], spec[at+1:]
		}
	} else if at := strings.IndexByte(spec, '@'); at >= 0 {
		name, version = spec[:at], spec[at+1:]
	}
	if name == "" || strings.ContainsAny(strings.TrimPrefix(name, "@"), "@ ") || (!strings.HasPrefix(name, "@") && strings.Contains(name, "/")) {
		return "", "", fmt.Errorf("invalid npm package name %q", name)
	}
	if strings.HasPrefix(name, "@") && (strings.Count(name, "/") != 1 || strings.HasPrefix(name, "@/")) {
		return "", "", fmt.Errorf("invalid npm package name %q", name)
	}
	if version != "" && version != "latest" && !npmExactVersion.MatchString(version) {
		return "", "", fmt.Errorf("npm package version must be exact or latest, got %q", version)
	}
	return name, version, nil
}

func parsePyPIspec(spec string) (string, string, error) {
	name := spec
	version := ""
	if at := strings.Index(spec, "=="); at >= 0 {
		name, version = spec[:at], spec[at+2:]
	} else if at := strings.IndexByte(spec, '@'); at >= 0 {
		name, version = spec[:at], spec[at+1:]
	}
	if name == "" || strings.ContainsAny(name, "@=<>!~*+ ") {
		return "", "", fmt.Errorf("invalid PyPI package name %q", name)
	}
	if version != "" && version != "latest" && !pypiExactVersion.MatchString(version) {
		return "", "", fmt.Errorf("PyPI package version must be exact or latest, got %q", version)
	}
	return name, version, nil
}

// RepositoryPath returns the repository path including ecosystem. It follows
// the package-store naming contract and is safe to append to a registry host.
func RepositoryPath(ecosystem Ecosystem, packageName string) string {
	name := strings.ToLower(packageName)
	switch ecosystem {
	case EcosystemNPM:
		name = strings.TrimPrefix(name, "@")
	case EcosystemPyPI:
		name = normalizePyPIName(name)
	}
	return string(ecosystem) + "/" + name
}

// ImageTag converts a resolved package version into a registry-safe tag.
func ImageTag(version string) string {
	var builder strings.Builder
	for _, char := range version {
		switch {
		case char == '+':
			builder.WriteByte('_')
		case (char >= 'a' && char <= 'z') || (char >= 'A' && char <= 'Z') || (char >= '0' && char <= '9') || char == '_' || char == '.' || char == '-':
			builder.WriteRune(char)
		default:
			builder.WriteByte('-')
		}
		if builder.Len() >= 128 {
			break
		}
	}
	return builder.String()[:minInt(builder.Len(), 128)]
}

func minInt(first, second int) int {
	if first < second {
		return first
	}
	return second
}

func privateRegistryEnvironment(environment map[string]string) string {
	for _, key := range []string{
		"NPM_CONFIG_REGISTRY", "npm_config_registry",
		"UV_INDEX_URL", "UV_DEFAULT_INDEX", "UV_INDEX", "UV_EXTRA_INDEX_URL",
		"PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL",
	} {
		if value := strings.TrimSpace(environment[key]); value != "" {
			return key
		}
	}
	return ""
}
