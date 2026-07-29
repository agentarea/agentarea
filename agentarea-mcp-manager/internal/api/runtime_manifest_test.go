package api

import (
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/gin-gonic/gin"
)

func TestRuntimeManifestForwardsValidatedProfile(t *testing.T) {
	dataPlane := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if got := r.URL.Query().Get("package_install"); got != "locked" {
			t.Fatalf("package_install = %q, want locked", got)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
  "schema_version": 1,
  "image_version": "locked-runtime",
  "managed_environment": "immutable",
  "python": {"version": "3.12.9", "executable": "/opt/runtime/venv/bin/python"},
  "node": {"version": "v22.1.0", "npm_version": ""},
  "tools": {}, "packages": {},
  "features": {"browser": "none", "managed_environment_mutation": false, "arbitrary_workspace_code": true}
}`))
	}))
	defer dataPlane.Close()

	backend := backends.NewDockerBackend(&config.Config{
		Container: config.ContainerConfig{SandboxExecutorURL: dataPlane.URL},
	}, slog.Default())
	handler := &Handler{backend: backend, logger: slog.Default()}
	gin.SetMode(gin.TestMode)
	router := gin.New()
	router.GET("/runtime/manifest", handler.runtimeManifest)

	request := httptest.NewRequest(http.MethodGet, "/runtime/manifest?package_install=locked", nil)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", response.Code, response.Body.String())
	}
}

func TestRuntimeManifestRejectsInvalidProfileBeforeBackend(t *testing.T) {
	handler := &Handler{logger: slog.Default()}
	gin.SetMode(gin.TestMode)
	router := gin.New()
	router.GET("/runtime/manifest", handler.runtimeManifest)

	request := httptest.NewRequest(http.MethodGet, "/runtime/manifest?package_install=invalid", nil)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)

	if response.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d: %s", response.Code, response.Body.String())
	}
}
