package packages

import (
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
)

// Config is where package images are stored and how packages are resolved.
type Config struct {
	// Repository is the registry repository package images are pushed to;
	// empty keeps them in the local container runtime's image store.
	Repository string
	// Runtime is the local CLI (docker or podman) used without a repository.
	Runtime string
	// Timeout bounds one pack workload, from start to stored image.
	Timeout time.Duration
	// NPMRegistry and PyPI resolve versions; private indexes are refused.
	NPMRegistry string
	PyPI        string
}

// LoadConfig reads AGENTAREA_MCP_PACKAGE_REPO, AGENTAREA_MCP_IMPORT_TIMEOUT,
// AGENTAREA_MCP_NPM_REGISTRY, AGENTAREA_MCP_PYPI_URL and AGENTAREA_MCP_RUNTIME.
func LoadConfig(l *config.Loader) Config {
	repo, _ := l.OptionalEnv("AGENTAREA_MCP_PACKAGE_REPO")
	return Config{
		Repository:  repo,
		Runtime:     l.OneOfEnv("AGENTAREA_MCP_RUNTIME", "docker", "docker", "podman"),
		Timeout:     l.DurationEnv("AGENTAREA_MCP_IMPORT_TIMEOUT", 15*time.Minute),
		NPMRegistry: l.StringEnv("AGENTAREA_MCP_NPM_REGISTRY", "https://registry.npmjs.org"),
		PyPI:        l.StringEnv("AGENTAREA_MCP_PYPI_URL", "https://pypi.org"),
	}
}
