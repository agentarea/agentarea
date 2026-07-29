package warmpool

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestGetRuntimeManifestValidatesDataPlaneResponse(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/runtime/manifest" {
			t.Fatalf("unexpected path %s", r.URL.Path)
		}
		if got := r.URL.Query().Get("package_install"); got != "allowed" {
			t.Fatalf("package_install = %q, want allowed", got)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
  "schema_version": 1,
  "image_version": "test-runtime",
  "managed_environment": "mutable",
  "python": {"version": "3.12.9", "executable": "/opt/runtime/venv/bin/python"},
  "node": {"version": "v22.1.0", "npm_version": "10.0.0"},
  "tools": {}, "packages": {},
  "features": {"browser": "none", "managed_environment_mutation": true, "arbitrary_workspace_code": true}
}`))
	}))
	defer server.Close()

	manifest, err := GetRuntimeManifest(context.Background(), server.URL, time.Second, "allowed")
	if err != nil {
		t.Fatal(err)
	}
	if manifest.ImageVersion != "test-runtime" || manifest.ManagedEnvironment != "mutable" {
		t.Fatalf("unexpected manifest: %#v", manifest)
	}
}

func TestGetRuntimeManifestRejectsProfileMismatch(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
  "schema_version": 1,
  "image_version": "test-runtime",
  "managed_environment": "mutable",
  "python": {"version": "3.12.9", "executable": "/opt/runtime/venv/bin/python"},
  "node": {"version": "v22.1.0", "npm_version": "10.0.0"},
  "tools": {}, "packages": {},
  "features": {"browser": "none", "managed_environment_mutation": true, "arbitrary_workspace_code": true}
}`))
	}))
	defer server.Close()

	_, err := GetRuntimeManifest(context.Background(), server.URL, time.Second, "locked")
	if err == nil || !strings.Contains(err.Error(), "does not support") {
		t.Fatalf("GetRuntimeManifest() error = %v, want profile mismatch", err)
	}
}
