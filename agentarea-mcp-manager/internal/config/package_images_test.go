package config

import (
	"testing"
	"time"
)

func TestLoadPackageImageConfig(t *testing.T) {
	t.Setenv("AGENTAREA_MCP_PACKAGE_REPO", "registry.example/packages")
	t.Setenv("AGENTAREA_MCP_IMPORT_TIMEOUT", "7m")
	t.Setenv("AGENTAREA_MCP_NPM_REGISTRY", "https://npm.example")
	t.Setenv("AGENTAREA_MCP_PYPI_URL", "https://pypi.example")

	cfg := Load()
	if cfg.PackageImages.Repository != "registry.example/packages" {
		t.Fatalf("repository = %q", cfg.PackageImages.Repository)
	}
	if cfg.PackageImages.ImportTimeout != 7*time.Minute {
		t.Fatalf("import timeout = %s", cfg.PackageImages.ImportTimeout)
	}
	if cfg.PackageImages.NPMRegistryURL != "https://npm.example" || cfg.PackageImages.PyPIURL != "https://pypi.example" {
		t.Fatalf("registry URLs = %q/%q", cfg.PackageImages.NPMRegistryURL, cfg.PackageImages.PyPIURL)
	}
}
