package api

import (
	"context"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/gin-gonic/gin"
)

func TestRuntimeManifestReturnsConfiguredRuntime(t *testing.T) {
	runtime := &controlRuntimeStub{runtimeManifest: func(_ context.Context) (*runtimeinfo.Manifest, error) {
		return &runtimeinfo.Manifest{SchemaVersion: 2, ImageVersion: "sandbox-runtime"}, nil
	}}
	handler := &Handler{sandboxRuntime: runtime, logger: slog.Default()}
	gin.SetMode(gin.TestMode)
	router := gin.New()
	router.GET("/runtime/manifest", handler.runtimeManifest)

	request := httptest.NewRequest(http.MethodGet, "/runtime/manifest", nil)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", response.Code, response.Body.String())
	}
}
