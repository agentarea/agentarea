package api

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/agentarea/mcp-manager/internal/backends"
)

type healthBackendProbe struct {
	backends.Backend
	listCalls int
}

func (b *healthBackendProbe) ListInstances(context.Context) ([]*backends.InstanceStatus, error) {
	b.listCalls++
	return nil, nil
}

func TestHealthCheckDoesNotScanRemoteWorkloadInventory(t *testing.T) {
	gin.SetMode(gin.TestMode)
	backend := &healthBackendProbe{}
	handler := &Handler{backend: backend, version: "test", startTime: time.Now()}
	recorder := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(recorder)
	ctx.Request = httptest.NewRequest(http.MethodGet, "/health", nil)

	handler.healthCheck(ctx)

	if recorder.Code != http.StatusOK {
		t.Fatalf("health status = %d, body=%s", recorder.Code, recorder.Body.String())
	}
	if backend.listCalls != 0 {
		t.Fatalf("health scanned workload inventory %d times", backend.listCalls)
	}
}
