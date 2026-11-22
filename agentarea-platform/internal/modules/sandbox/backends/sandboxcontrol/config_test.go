package sandboxcontrol

import (
	"strings"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	redis "github.com/redis/go-redis/v9"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
)

const testMaxExecutionTimeoutSeconds = 1800

func validControlEnv() map[string]string {
	return map[string]string{
		"AGENTAREA_SANDBOX_RECORD_TTL":       "1h",
		"AGENTAREA_SANDBOX_MAX_EXEC_SECONDS": "1800",
		"AGENTAREA_SANDBOX_EXEC_SECONDS":     "120",
		"AGENTAREA_SANDBOX_QUEUE_TIMEOUT":    "5m",
		"AGENTAREA_SANDBOX_COMPLETION_GRACE": "1m",
	}
}

func loadControl(t *testing.T, vars map[string]string) (Config, error) {
	t.Helper()
	l := config.FromMap(vars)
	cfg := LoadConfig(l)
	return cfg, l.Err()
}

func TestLoadConfigRejectsMissingExecutionRecordTTL(t *testing.T) {
	vars := validControlEnv()
	delete(vars, "AGENTAREA_SANDBOX_RECORD_TTL")
	if _, err := loadControl(t, vars); err == nil || !strings.Contains(err.Error(), "AGENTAREA_SANDBOX_RECORD_TTL") {
		t.Fatalf("missing AGENTAREA_SANDBOX_RECORD_TTL unexpectedly resolved to a default: %v", err)
	}
}

func TestLoadConfigRejectsMalformedExecutionRecordTTL(t *testing.T) {
	for _, value := range []string{"soon", "0", "-1h"} {
		vars := validControlEnv()
		vars["AGENTAREA_SANDBOX_RECORD_TTL"] = value
		if _, err := loadControl(t, vars); err == nil {
			t.Fatalf("AGENTAREA_SANDBOX_RECORD_TTL=%q unexpectedly resolved", value)
		}
	}
}

func TestLoadConfigResolvesExecutionRecordTTL(t *testing.T) {
	vars := validControlEnv()
	vars["AGENTAREA_SANDBOX_RECORD_TTL"] = "36h"
	vars["AGENTAREA_SANDBOX_REDIS_PREFIX"] = "agentarea:test"
	cfg, err := loadControl(t, vars)
	if err != nil {
		t.Fatalf("LoadConfig() error = %v", err)
	}
	if cfg.ExecutionRecordTTL != 36*time.Hour {
		t.Fatalf("ExecutionRecordTTL = %s, want 36h", cfg.ExecutionRecordTTL)
	}
	if cfg.MaxExecutionTimeoutSeconds != testMaxExecutionTimeoutSeconds {
		t.Fatalf("MaxExecutionTimeoutSeconds = %d", cfg.MaxExecutionTimeoutSeconds)
	}
	if cfg.RedisPrefix != "agentarea:test" {
		t.Fatalf("resolved config = %+v", cfg)
	}
}

func TestLoadConfigRejectsMissingOrInvalidMaximumExecutionTimeout(t *testing.T) {
	for _, value := range []string{"", "0", "-1", "later"} {
		vars := validControlEnv()
		vars["AGENTAREA_SANDBOX_MAX_EXEC_SECONDS"] = value
		if _, err := loadControl(t, vars); err == nil {
			t.Fatalf("AGENTAREA_SANDBOX_MAX_EXEC_SECONDS=%q unexpectedly resolved", value)
		}
	}
}

// The store must not re-introduce a retention default of its own.
func TestNewRedisStoreRejectsNonPositiveTTL(t *testing.T) {
	client := redis.NewClient(&redis.Options{Addr: miniredis.RunT(t).Addr()})
	t.Cleanup(func() { _ = client.Close() })
	policy := testExecutionPolicy(testMaxExecutionTimeoutSeconds)
	if _, err := NewRedisStore(client, "agentarea:test", 0, policy); err == nil {
		t.Fatal("zero TTL unexpectedly accepted")
	}
	if _, err := NewRedisStore(client, "agentarea:test", -time.Second, policy); err == nil {
		t.Fatal("negative TTL unexpectedly accepted")
	}
}

func TestNewRedisStoreRequiresAClient(t *testing.T) {
	if _, err := NewRedisStore(nil, "agentarea:test", time.Hour, testExecutionPolicy(testMaxExecutionTimeoutSeconds)); err == nil {
		t.Fatal("store without a Redis client unexpectedly built")
	}
}

func TestLoadConfigRejectsMissingExecutionAdmissionPolicy(t *testing.T) {
	for _, missing := range []string{
		"AGENTAREA_SANDBOX_EXEC_SECONDS",
		"AGENTAREA_SANDBOX_QUEUE_TIMEOUT",
		"AGENTAREA_SANDBOX_COMPLETION_GRACE",
	} {
		t.Run(missing, func(t *testing.T) {
			vars := validControlEnv()
			delete(vars, missing)
			if _, err := loadControl(t, vars); err == nil || !strings.Contains(err.Error(), missing) {
				t.Fatalf("missing %s unexpectedly resolved: %v", missing, err)
			}
		})
	}
}
