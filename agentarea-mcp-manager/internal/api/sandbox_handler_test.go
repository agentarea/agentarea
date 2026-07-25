package api

import (
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

func TestSandboxCleanupRouteUsesTaskIdentityOnly(t *testing.T) {
	gin.SetMode(gin.TestMode)
	router := gin.New()
	handler := &Handler{logger: slog.Default()}
	handler.SetupRoutes(router)

	routes := make(map[string]bool)
	for _, route := range router.Routes() {
		routes[route.Method+" "+route.Path] = true
	}
	if !routes["DELETE /sandbox/task/:id"] {
		t.Fatal("task cleanup route is not registered")
	}
	if routes["DELETE /sandbox/workflow/:id"] {
		t.Fatal("workflow cleanup route must not be registered")
	}
}

func TestSandboxCleanupRequiresDedicatedBearerBeforeFeatureCheck(t *testing.T) {
	t.Setenv(sandboxCleanupAuthSecretEnv, "cleanup-secret-for-tests")
	t.Setenv("MCP_FEATURE_WARM_POOL", "false")

	for _, test := range []struct {
		name          string
		authorization string
		wantStatus    int
	}{
		{name: "missing", wantStatus: http.StatusUnauthorized},
		{name: "wrong", authorization: "Bearer wrong-secret", wantStatus: http.StatusUnauthorized},
		{name: "activation secret", authorization: "Bearer activation-secret-for-tests", wantStatus: http.StatusUnauthorized},
		{name: "cleanup secret", authorization: "Bearer cleanup-secret-for-tests", wantStatus: http.StatusNoContent},
	} {
		t.Run(test.name, func(t *testing.T) {
			recorder := httptest.NewRecorder()
			context, _ := gin.CreateTestContext(recorder)
			context.Params = gin.Params{{Key: "id", Value: "task-123"}}
			context.Request = httptest.NewRequest(http.MethodDelete, "/sandbox/task/task-123", nil)
			if test.authorization != "" {
				context.Request.Header.Set("Authorization", test.authorization)
			}

			handler := &Handler{logger: slog.Default()}
			handler.deleteSandboxTask(context)
			context.Writer.WriteHeaderNow()

			if recorder.Code != test.wantStatus {
				t.Fatalf("status = %d, want %d; body=%s", recorder.Code, test.wantStatus, recorder.Body.String())
			}
		})
	}
}

func TestSandboxCleanupFailsClosedWithoutConfiguredSecret(t *testing.T) {
	t.Setenv(sandboxCleanupAuthSecretEnv, "")
	recorder := httptest.NewRecorder()
	context, _ := gin.CreateTestContext(recorder)
	context.Params = gin.Params{{Key: "id", Value: "task-123"}}
	context.Request = httptest.NewRequest(http.MethodDelete, "/sandbox/task/task-123", nil)
	context.Request.Header.Set("Authorization", "Bearer any-presented-secret")

	handler := &Handler{logger: slog.Default()}
	handler.deleteSandboxTask(context)
	context.Writer.WriteHeaderNow()

	if recorder.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want %d; body=%s", recorder.Code, http.StatusUnauthorized, recorder.Body.String())
	}
}

func TestSandboxTaskIdleTTL(t *testing.T) {
	t.Setenv("SANDBOX_TASK_IDLE_TTL", "42s")
	if got := sandboxTaskIdleTTL(); got != 42*time.Second {
		t.Fatalf("sandboxTaskIdleTTL() = %s, want 42s", got)
	}
}

func TestSandboxTaskIdleTTLIgnoresWorkflowSetting(t *testing.T) {
	t.Setenv("SANDBOX_TASK_IDLE_TTL", "")
	t.Setenv("SANDBOX_WORKFLOW_IDLE_TTL", "1s")
	if got := sandboxTaskIdleTTL(); got != 15*time.Minute {
		t.Fatalf("sandboxTaskIdleTTL() = %s, want task default", got)
	}
}
