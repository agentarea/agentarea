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

// GET /containers and /containers/:service are manager-bearer-protected
// inspection routes. Keep Environment redacted as defense-in-depth: the
// resolved values are the secrets the containers actually run with, and
// exposing them to an internal caller is still a credential leak.

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

func TestListContainersDoesNotDiscloseContainerEnvironments(t *testing.T) {
	recorder := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(recorder)
	ctx.Request = httptest.NewRequest(http.MethodGet, "/containers", nil)

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
	recorder := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(recorder)
	ctx.Request = httptest.NewRequest(http.MethodGet, "/containers/telegram-mcp", nil)
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
