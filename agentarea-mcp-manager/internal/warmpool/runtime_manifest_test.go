package warmpool

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestGetRuntimeManifestValidatesDataPlaneResponse(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/runtime/manifest" {
			t.Fatalf("unexpected path %s", r.URL.Path)
		}
		if r.URL.RawQuery != "" {
			t.Fatalf("unexpected query %q", r.URL.RawQuery)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
  "schema_version": 2,
  "managed_environment": "mutable",
  "image_version": "test-runtime",
  "python": {"version": "3.12.9", "executable": "/opt/runtime/venv/bin/python"},
  "node": {"version": "v22.1.0", "npm_version": "10.0.0"},
  "tools": {}, "packages": {},
  "features": {"browser": "none", "managed_environment_mutation": true, "arbitrary_workspace_code": true},
  "execution_supervisor": {"path":"/usr/local/bin/agentarea-exec-supervisor","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","protocol_version":1,"command_uid":10001,"command_gid":10001}
}`))
	}))
	defer server.Close()

	manifest, err := GetRuntimeManifest(context.Background(), server.URL, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if manifest.ImageVersion != "test-runtime" {
		t.Fatalf("unexpected manifest: %#v", manifest)
	}
}
