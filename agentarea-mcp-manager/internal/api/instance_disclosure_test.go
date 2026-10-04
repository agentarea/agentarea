package api

import (
	"context"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/sandboxcontrol"
)

// The manager inspection API is an internal surface protected by the shared
// MCP gateway bearer. Response redaction remains defense in depth.
const managerInspectionTestSecret = "mcp-gateway-inspection-secret-for-tests" // pragma: allowlist secret

type disclosureBackendStub struct {
	status *backends.InstanceStatus
}

func (b *disclosureBackendStub) CreateInstance(context.Context, *backends.InstanceSpec) (*backends.InstanceResult, error) {
	return nil, nil
}
func (b *disclosureBackendStub) DeleteInstance(context.Context, string) error { return nil }
func (b *disclosureBackendStub) GetInstanceStatus(context.Context, string) (*backends.InstanceStatus, error) {
	return b.status, nil
}
func (b *disclosureBackendStub) ListInstances(context.Context) ([]*backends.InstanceStatus, error) {
	return []*backends.InstanceStatus{b.status}, nil
}
func (b *disclosureBackendStub) UpdateInstance(context.Context, string, *backends.InstanceSpec) error {
	return nil
}
func (b *disclosureBackendStub) PerformHealthCheck(context.Context, string) (*backends.HealthCheckResult, error) {
	return &backends.HealthCheckResult{Healthy: true, Status: "running"}, nil
}
func (b *disclosureBackendStub) Initialize(context.Context) error { return nil }
func (b *disclosureBackendStub) Shutdown(context.Context) error   { return nil }

const disclosedSecret = "1AZWarzwBu32uEudLyEwrynvwayCBkkv-test-session"

func disclosureRouter(t *testing.T) *gin.Engine {
	t.Helper()
	t.Setenv("AGENTAREA_SANDBOX_RECORD_TTL", "24h")
	t.Setenv("AGENTAREA_MCP_GATEWAY_SECRET", managerInspectionTestSecret)
	gin.SetMode(gin.TestMode)

	backend := &disclosureBackendStub{status: &backends.InstanceStatus{
		ID:          "container-1",
		Name:        "659b1561-79bf-424d-b707-7897a4304c98",
		ServiceName: "659b1561-79bf-424d-b707-7897a4304c98",
		Status:      "running",
		Image:       "registry.example/pool/telegram-mcp:1",
		Port:        8765,
		Environment: map[string]string{
			"TELEGRAM_SESSION_STRING": disclosedSecret,
			"MCP_PORT":                "8765",
		},
	}}

	handler, err := NewHandler(
		backend, containerDisclosureManager(),
		slog.New(slog.NewTextHandler(nopWriter{}, nil)),
		"test",
		SandboxPolicy{},
		sandboxcontrol.Config{
			RedisURL:                       "redis://127.0.0.1:6379",
			ExecutionRecordTTL:             24 * time.Hour,
			DefaultExecutionTimeoutSeconds: 120,
			MaxExecutionTimeoutSeconds:     1800,
			QueueTimeout:                   5 * time.Minute,
			CompletionGrace:                2 * time.Minute,
		},
		&controlRuntimeStub{},
	)
	if err != nil {
		t.Fatal(err)
	}
	router := gin.New()
	handler.SetupRoutes(router)
	return router
}

func managerInspectionRequest(method, target string) *http.Request {
	request := httptest.NewRequest(method, target, nil)
	request.Header.Set("Authorization", "Bearer "+managerInspectionTestSecret)
	return request
}

func TestInstanceInspectionRequiresManagerBearer(t *testing.T) {
	router := disclosureRouter(t)
	unauthorized := httptest.NewRecorder()
	router.ServeHTTP(unauthorized, httptest.NewRequest(http.MethodGet, "/instances", nil))
	if unauthorized.Code != http.StatusUnauthorized {
		t.Fatalf("unauthenticated status = %d, want 401; body=%s", unauthorized.Code, unauthorized.Body.String())
	}

	authorized := httptest.NewRecorder()
	router.ServeHTTP(authorized, managerInspectionRequest(http.MethodGet, "/instances"))
	if authorized.Code != http.StatusOK {
		t.Fatalf("authenticated status = %d, want 200; body=%s", authorized.Code, authorized.Body.String())
	}
}

func TestMonitoringInspectionRequiresManagerBearer(t *testing.T) {
	router := disclosureRouter(t)
	unauthorized := httptest.NewRecorder()
	router.ServeHTTP(unauthorized, httptest.NewRequest(http.MethodGet, "/monitoring/status", nil))
	if unauthorized.Code != http.StatusUnauthorized {
		t.Fatalf("unauthenticated status = %d, want 401; body=%s", unauthorized.Code, unauthorized.Body.String())
	}

	authorized := httptest.NewRecorder()
	router.ServeHTTP(authorized, managerInspectionRequest(http.MethodGet, "/monitoring/status"))
	if authorized.Code != http.StatusOK {
		t.Fatalf("authenticated status = %d, want 200; body=%s", authorized.Code, authorized.Body.String())
	}
}
func TestContainerInspectionRequiresManagerBearer(t *testing.T) {
	router := disclosureRouter(t)
	unauthorized := httptest.NewRecorder()
	router.ServeHTTP(unauthorized, httptest.NewRequest(http.MethodGet, "/containers", nil))
	if unauthorized.Code != http.StatusUnauthorized {
		t.Fatalf("unauthenticated status = %d, want 401; body=%s", unauthorized.Code, unauthorized.Body.String())
	}

	authorized := httptest.NewRecorder()
	router.ServeHTTP(authorized, managerInspectionRequest(http.MethodGet, "/containers"))
	if authorized.Code != http.StatusOK {
		t.Fatalf("authenticated status = %d, want 200; body=%s", authorized.Code, authorized.Body.String())
	}
}

type nopWriter struct{}

func (nopWriter) Write(p []byte) (int, error) { return len(p), nil }

func TestGetInstanceDoesNotDiscloseTheInstanceEnvironment(t *testing.T) {
	router := disclosureRouter(t)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, managerInspectionRequest(
		http.MethodGet, "/instances/659b1561-79bf-424d-b707-7897a4304c98",
	))

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	if strings.Contains(recorder.Body.String(), disclosedSecret) {
		t.Error("authenticated instance inspection returned the workload's credentials")
	}
	// The route still has to be useful: redacting must not empty the response.
	if !strings.Contains(recorder.Body.String(), "running") {
		t.Errorf("instance state went missing along with the secrets: %s", recorder.Body.String())
	}
}

func TestListInstancesDoesNotDiscloseInstanceEnvironments(t *testing.T) {
	router := disclosureRouter(t)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, managerInspectionRequest(http.MethodGet, "/instances"))

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	if strings.Contains(recorder.Body.String(), disclosedSecret) {
		t.Error("authenticated instance listing returned workload credentials")
	}
}
