package api

import (
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/container"
	"github.com/agentarea/mcp-manager/internal/models"
)

// GET /containers and /containers/:service serialize models.Container
// straight to JSON, including Environment — the resolved secret values the
// container actually runs with. Unlike the instance inspection routes, these
// carried neither redaction nor authentication, so any workload that could
// reach the manager could read every container's credentials.

const containerDisclosedSecret = "1AZWarzwBu32uEudLyEwrynvwayCBkkv-test-container-secret" // pragma: allowlist secret

func containerDisclosureManager() *container.Manager {
	// Runtime "true" lets GetContainerStatus (used by checkContainerHealth)
	// shell out successfully without a real container runtime; its output is
	// ignored beyond mapping to an unhealthy status.
	cfg := &config.Config{Container: config.ContainerConfig{Runtime: "true"}}
	return container.NewManagerWithContainers(cfg, map[string]*models.Container{
		"telegram-mcp": {
			ID:          "container-1",
			Name:        "telegram-mcp",
			ServiceName: "telegram-mcp",
			Status:      models.StatusRunning,
			Image:       "registry.example/pool/telegram-mcp:1",
			Port:        8765,
			Environment: map[string]string{
				"TELEGRAM_SESSION_STRING": containerDisclosedSecret,
				"MCP_PORT":                "8765",
			},
		},
	})
}

func TestListContainersRequiresInspectionSecret(t *testing.T) {
	t.Setenv(containerInspectionAuthSecretEnv, "")
	recorder := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(recorder)
	ctx.Request = httptest.NewRequest(http.MethodGet, "/containers", nil)
	ctx.Request.Header.Set("Authorization", "Bearer anything")

	(&Handler{logger: slog.Default(), containerManager: containerDisclosureManager()}).listContainers(ctx)

	if recorder.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want 401; body=%s", recorder.Code, recorder.Body.String())
	}
}

func TestGetContainerRequiresInspectionSecret(t *testing.T) {
	t.Setenv(containerInspectionAuthSecretEnv, "")
	recorder := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(recorder)
	ctx.Request = httptest.NewRequest(http.MethodGet, "/containers/telegram-mcp", nil)
	ctx.Params = gin.Params{{Key: "service", Value: "telegram-mcp"}}

	(&Handler{logger: slog.Default(), containerManager: containerDisclosureManager()}).getContainer(ctx)

	if recorder.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want 401; body=%s", recorder.Code, recorder.Body.String())
	}
}

func TestListContainersDoesNotDiscloseContainerEnvironments(t *testing.T) {
	t.Setenv(containerInspectionAuthSecretEnv, "inspection-secret")
	recorder := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(recorder)
	ctx.Request = httptest.NewRequest(http.MethodGet, "/containers", nil)
	ctx.Request.Header.Set("Authorization", "Bearer inspection-secret")

	(&Handler{logger: slog.Default(), containerManager: containerDisclosureManager()}).listContainers(ctx)

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", recorder.Code, recorder.Body.String())
	}
	if strings.Contains(recorder.Body.String(), containerDisclosedSecret) {
		t.Error("container listing returned workload credentials")
	}
	if !strings.Contains(recorder.Body.String(), "telegram-mcp") {
		t.Errorf("container listing went missing along with the secrets: %s", recorder.Body.String())
	}
}

func TestGetContainerDoesNotDiscloseTheContainerEnvironment(t *testing.T) {
	t.Setenv(containerInspectionAuthSecretEnv, "inspection-secret")
	recorder := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(recorder)
	ctx.Request = httptest.NewRequest(http.MethodGet, "/containers/telegram-mcp", nil)
	ctx.Request.Header.Set("Authorization", "Bearer inspection-secret")
	ctx.Params = gin.Params{{Key: "service", Value: "telegram-mcp"}}

	(&Handler{logger: slog.Default(), containerManager: containerDisclosureManager()}).getContainer(ctx)

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", recorder.Code, recorder.Body.String())
	}
	if strings.Contains(recorder.Body.String(), containerDisclosedSecret) {
		t.Error("container inspection returned the workload's credentials")
	}
	if !strings.Contains(recorder.Body.String(), "running") {
		t.Errorf("container state went missing along with the secrets: %s", recorder.Body.String())
	}
}

func TestCheckContainerHealthDoesNotDiscloseTheContainerEnvironment(t *testing.T) {
	recorder := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(recorder)
	ctx.Request = httptest.NewRequest(http.MethodGet, "/containers/telegram-mcp/health", nil)
	ctx.Params = gin.Params{{Key: "service", Value: "telegram-mcp"}}

	(&Handler{logger: slog.Default(), containerManager: containerDisclosureManager()}).checkContainerHealth(ctx)

	if strings.Contains(recorder.Body.String(), containerDisclosedSecret) {
		t.Errorf("container health check returned the workload's credentials: %s", recorder.Body.String())
	}
}
