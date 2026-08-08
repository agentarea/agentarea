package runtimeinfo

import (
	"encoding/json"
	"fmt"
	"io"
	"os"

	"github.com/agentarea/mcp-manager/internal/execsupervisor"
)

const DefaultManifestPath = "/etc/agentarea/runtime.json"

type Manifest struct {
	SchemaVersion       int                        `json:"schema_version"`
	ImageVersion        string                     `json:"image_version"`
	Python              PythonRuntime              `json:"python"`
	Node                NodeRuntime                `json:"node"`
	Tools               map[string]string          `json:"tools"`
	Packages            map[string]string          `json:"packages"`
	Features            Features                   `json:"features"`
	ExecutionSupervisor execsupervisor.Attestation `json:"execution_supervisor"`
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
	Browser                string `json:"browser"`
	ArbitraryWorkspaceCode bool   `json:"arbitrary_workspace_code"`
}

func (m Manifest) Validate() error {
	if m.SchemaVersion != 2 {
		return fmt.Errorf("unsupported runtime manifest schema_version %d", m.SchemaVersion)
	}
	if m.ImageVersion == "" || m.Python.Version == "" || m.Node.Version == "" {
		return fmt.Errorf("runtime manifest is missing image/python/node version")
	}
	if m.Features.Browser != "none" {
		return fmt.Errorf("browser capability must remain none in this runtime")
	}
	if !m.Features.ArbitraryWorkspaceCode {
		return fmt.Errorf("runtime must disclose arbitrary workspace code capability")
	}
	if err := m.ExecutionSupervisor.Validate(); err != nil {
		return fmt.Errorf("runtime execution supervisor: %w", err)
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
