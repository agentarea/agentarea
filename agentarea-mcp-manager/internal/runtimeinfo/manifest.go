package runtimeinfo

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
)

const DefaultManifestPath = "/etc/agentarea/runtime.json"

const (
	PackageInstallAllowed = "allowed"
	PackageInstallLocked  = "locked"
)

type Manifest struct {
	SchemaVersion      int               `json:"schema_version"`
	ImageVersion       string            `json:"image_version"`
	ManagedEnvironment string            `json:"managed_environment"`
	Python             PythonRuntime     `json:"python"`
	Node               NodeRuntime       `json:"node"`
	Tools              map[string]string `json:"tools"`
	Packages           map[string]string `json:"packages"`
	Features           Features          `json:"features"`
}

type PythonRuntime struct {
	Version    string `json:"version"`
	Executable string `json:"executable"`
}

type NodeRuntime struct {
	Version    string `json:"version"`
	NPMVersion string `json:"npm_version"`
}

type Features struct {
	Browser                    string `json:"browser"`
	ManagedEnvironmentMutation bool   `json:"managed_environment_mutation"`
	ArbitraryWorkspaceCode     bool   `json:"arbitrary_workspace_code"`
}

func (m Manifest) Validate() error {
	if m.SchemaVersion != 1 {
		return fmt.Errorf("unsupported runtime manifest schema_version %d", m.SchemaVersion)
	}
	if m.ImageVersion == "" || m.Python.Version == "" || m.Node.Version == "" {
		return fmt.Errorf("runtime manifest is missing image/python/node version")
	}
	if m.ManagedEnvironment != "mutable" && m.ManagedEnvironment != "immutable" {
		return fmt.Errorf("managed_environment must be mutable or immutable")
	}
	if m.Features.Browser != "none" {
		return fmt.Errorf("browser capability must remain none in this runtime")
	}
	if m.Features.ManagedEnvironmentMutation != (m.ManagedEnvironment == "mutable") {
		return fmt.Errorf("managed environment feature disagrees with profile")
	}
	if !m.Features.ArbitraryWorkspaceCode {
		return fmt.Errorf("runtime must disclose arbitrary workspace code capability")
	}
	return nil
}

// SupportsPackageInstall reports whether this image enforces the requested
// managed-environment profile. Mixed profiles require separate runtime pools;
// a request is never silently weakened to the active image's profile.
func (m Manifest) SupportsPackageInstall(profile string) bool {
	switch profile {
	case PackageInstallAllowed:
		return m.ManagedEnvironment == "mutable" && m.Features.ManagedEnvironmentMutation
	case PackageInstallLocked:
		return m.ManagedEnvironment == "immutable" && !m.Features.ManagedEnvironmentMutation
	default:
		return false
	}
}

func ValidatePackageInstall(profile string) error {
	if profile != PackageInstallAllowed && profile != PackageInstallLocked {
		return fmt.Errorf("package_install must be allowed or locked")
	}
	return nil
}

func Load(path string) (*Manifest, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open runtime manifest: %w", err)
	}
	defer file.Close()

	decoder := json.NewDecoder(io.LimitReader(file, 2*1024*1024))
	decoder.DisallowUnknownFields()
	var manifest Manifest
	if err := decoder.Decode(&manifest); err != nil {
		return nil, fmt.Errorf("decode runtime manifest: %w", err)
	}
	if err := manifest.Validate(); err != nil {
		return nil, err
	}
	return &manifest, nil
}

func PathFromEnv() string {
	if path := os.Getenv("RUNTIME_MANIFEST_PATH"); path != "" {
		return path
	}
	return DefaultManifestPath
}
