package runtimeinfo

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadValidatesRuntimeContract(t *testing.T) {
	path := filepath.Join(t.TempDir(), "runtime.json")
	payload := `{
  "schema_version": 2,
  "managed_environment": "mutable",
  "image_version": "test",
  "python": {"version": "3.12.9", "executable": "/opt/runtime/venv/bin/python"},
  "node": {"version": "v22.1.0", "npm_version": "10.0.0"},
  "tools": {"git": "git version 2.0"},
  "packages": {"openpyxl": "3.1.5"},
  "features": {"browser": "none", "managed_environment_mutation": true, "arbitrary_workspace_code": true},
  "execution_supervisor": {"path":"/usr/local/bin/agentarea-exec-supervisor","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","protocol_version":1,"command_uid":10001,"command_gid":10001}
}`
	if err := os.WriteFile(path, []byte(payload), 0o600); err != nil {
		t.Fatal(err)
	}
	manifest, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if manifest.ImageVersion != "test" || !manifest.Features.ArbitraryWorkspaceCode {
		t.Fatalf("unexpected manifest: %#v", manifest)
	}
}

func TestLoadRejectsUnknownRuntimeFields(t *testing.T) {
	path := filepath.Join(t.TempDir(), "runtime.json")
	payload := `{
  "schema_version": 2,
  "managed_environment": "mutable",
  "image_version": "test",
	  "runtime_profile": "unexpected",
  "python": {"version": "3.12.9", "executable": "/opt/runtime/venv/bin/python"},
  "node": {"version": "v22.1.0", "npm_version": "10.0.0"},
  "tools": {}, "packages": {},
  "features": {"browser": "none", "managed_environment_mutation": true, "arbitrary_workspace_code": true},
  "execution_supervisor": {"path":"/usr/local/bin/agentarea-exec-supervisor","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","protocol_version":1,"command_uid":10001,"command_gid":10001}
}`
	if err := os.WriteFile(path, []byte(payload), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := Load(path); err == nil {
		t.Fatal("expected unknown runtime field to be rejected")
	}
}
