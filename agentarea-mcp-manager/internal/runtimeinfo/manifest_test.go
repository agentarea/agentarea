package runtimeinfo

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadValidatesManagedEnvironmentContract(t *testing.T) {
	path := filepath.Join(t.TempDir(), "runtime.json")
	payload := `{
  "schema_version": 1,
  "image_version": "test",
  "managed_environment": "immutable",
  "python": {"version": "3.12.9", "executable": "/opt/runtime/venv/bin/python"},
  "node": {"version": "v22.1.0", "npm_version": "10.0.0"},
  "tools": {"git": "git version 2.0"},
  "packages": {"openpyxl": "3.1.5"},
  "features": {"browser": "none", "managed_environment_mutation": false, "arbitrary_workspace_code": true}
}`
	if err := os.WriteFile(path, []byte(payload), 0o600); err != nil {
		t.Fatal(err)
	}
	manifest, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if manifest.ManagedEnvironment != "immutable" || manifest.Features.ManagedEnvironmentMutation {
		t.Fatalf("unexpected manifest: %#v", manifest)
	}
}

func TestLoadRejectsProfileFeatureMismatch(t *testing.T) {
	path := filepath.Join(t.TempDir(), "runtime.json")
	payload := `{
  "schema_version": 1,
  "image_version": "test",
  "managed_environment": "immutable",
  "python": {"version": "3.12.9", "executable": "/opt/runtime/venv/bin/python"},
  "node": {"version": "v22.1.0", "npm_version": "10.0.0"},
  "tools": {}, "packages": {},
  "features": {"browser": "none", "managed_environment_mutation": true, "arbitrary_workspace_code": true}
}`
	if err := os.WriteFile(path, []byte(payload), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := Load(path); err == nil {
		t.Fatal("expected inconsistent manifest to be rejected")
	}
}

func TestManifestSupportsOnlyMatchingPackageInstallProfile(t *testing.T) {
	mutable := Manifest{
		ManagedEnvironment: "mutable",
		Features:           Features{ManagedEnvironmentMutation: true},
	}
	immutable := Manifest{
		ManagedEnvironment: "immutable",
		Features:           Features{ManagedEnvironmentMutation: false},
	}
	if !mutable.SupportsPackageInstall(PackageInstallAllowed) || mutable.SupportsPackageInstall(PackageInstallLocked) {
		t.Fatal("mutable runtime did not enforce allowed-only selection")
	}
	if !immutable.SupportsPackageInstall(PackageInstallLocked) || immutable.SupportsPackageInstall(PackageInstallAllowed) {
		t.Fatal("immutable runtime did not enforce locked-only selection")
	}
	if err := ValidatePackageInstall(""); err == nil {
		t.Fatal("missing package_install profile was accepted")
	}
}
