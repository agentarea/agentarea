package api

import (
	"log/slog"
	"net/http"
	"os"
	"testing"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/agentarea/mcp-manager/internal/sandboxcontrol"
)

// TestWorkloadMutationIsNotReachableOutsideTheGateway pins the single-owner
// rule. These routes used to create and destroy MCP workloads directly, which
// meant: no mcp_runtime_instances row (so the reaper could never reclaim the
// workload), no lifecycle advisory lock (so it raced the gateway's serialized
// cold start), and no active-lease check on delete (so it could tear a workload
// down mid-request). Re-registering any of them reopens all three.
func TestWorkloadMutationIsNotReachableOutsideTheGateway(t *testing.T) {
	t.Setenv("SANDBOX_EXECUTION_RECORD_TTL", "24h")
	gin.SetMode(gin.TestMode)

	handler, err := NewHandler(
		nil, nil,
		slog.New(slog.NewTextHandler(os.Stdout, nil)),
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

	registered := map[string]bool{}
	for _, route := range router.Routes() {
		registered[route.Method+" "+route.Path] = true
	}

	for _, forbidden := range []string{
		http.MethodPost + " /instances",
		http.MethodPut + " /instances/:id",
		http.MethodDelete + " /instances/:id",
		http.MethodPost + " /containers",
		http.MethodDelete + " /containers/:service",
	} {
		if registered[forbidden] {
			t.Errorf("%s bypasses the demand gateway's lifecycle ownership", forbidden)
		}
	}

	// Inspection must stay available — it mutates nothing.
	for _, allowed := range []string{
		http.MethodGet + " /instances",
		http.MethodGet + " /instances/:id",
		http.MethodGet + " /health",
	} {
		if !registered[allowed] {
			t.Errorf("%s should remain available for inspection", allowed)
		}
	}
}

func TestNewHandlerRequiresCompleteSandboxControlRuntime(t *testing.T) {
	t.Setenv("SANDBOX_EXECUTION_RECORD_TTL", "24h")
	_, err := NewHandler(
		nil,
		nil,
		slog.Default(),
		"test",
		SandboxPolicy{},
		sandboxcontrol.Config{
			RedisURL: "redis://127.0.0.1:6379", ExecutionRecordTTL: 24 * time.Hour,
			DefaultExecutionTimeoutSeconds: 120, MaxExecutionTimeoutSeconds: 1800,
			QueueTimeout: 5 * time.Minute, CompletionGrace: 2 * time.Minute,
		},
		nil,
	)
	if err == nil || err.Error() != "sandbox control runtime is required" {
		t.Fatalf("NewHandler() error = %v, want required control runtime", err)
	}
}
