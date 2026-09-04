package sandboxcontrol

import (
	"testing"
	"time"
)

const (
	testRedisURL                   = "redis://127.0.0.1:6379"
	testMaxExecutionTimeoutSeconds = 1800
)

func TestLoadConfigRejectsMissingExecutionRecordTTL(t *testing.T) {
	t.Setenv("SANDBOX_EXECUTION_RECORD_TTL", "")
	if _, err := LoadConfigFromEnv(testRedisURL); err == nil {
		t.Fatal("missing SANDBOX_EXECUTION_RECORD_TTL unexpectedly resolved to a default")
	}
}

func TestLoadConfigRejectsMalformedExecutionRecordTTL(t *testing.T) {
	for _, value := range []string{"soon", "0", "-1h"} {
		t.Setenv("SANDBOX_EXECUTION_RECORD_TTL", value)
		if _, err := LoadConfigFromEnv(testRedisURL); err == nil {
			t.Fatalf("SANDBOX_EXECUTION_RECORD_TTL=%q unexpectedly resolved", value)
		}
	}
}

func TestLoadConfigResolvesExecutionRecordTTL(t *testing.T) {
	t.Setenv("SANDBOX_EXECUTION_RECORD_TTL", "36h")
	t.Setenv("SANDBOX_MAX_EXECUTION_TIMEOUT_SECONDS", "1800")
	t.Setenv("SANDBOX_DEFAULT_EXECUTION_TIMEOUT_SECONDS", "120")
	t.Setenv("SANDBOX_EXECUTION_QUEUE_TIMEOUT", "5m")
	t.Setenv("SANDBOX_EXECUTION_COMPLETION_GRACE", "1m")
	t.Setenv("SANDBOX_CONTROL_REDIS_PREFIX", "agentarea:test")
	cfg, err := LoadConfigFromEnv(testRedisURL)
	if err != nil {
		t.Fatalf("LoadConfigFromEnv() error = %v", err)
	}
	if cfg.ExecutionRecordTTL != 36*time.Hour {
		t.Fatalf("ExecutionRecordTTL = %s, want 36h", cfg.ExecutionRecordTTL)
	}
	if cfg.MaxExecutionTimeoutSeconds != testMaxExecutionTimeoutSeconds {
		t.Fatalf("MaxExecutionTimeoutSeconds = %d", cfg.MaxExecutionTimeoutSeconds)
	}
	if cfg.RedisPrefix != "agentarea:test" || cfg.RedisURL != testRedisURL {
		t.Fatalf("resolved config = %+v", cfg)
	}
}

func TestLoadConfigRejectsMissingOrInvalidMaximumExecutionTimeout(t *testing.T) {
	t.Setenv("SANDBOX_EXECUTION_RECORD_TTL", "1h")
	for _, value := range []string{"", "0", "-1", "later"} {
		t.Setenv("SANDBOX_MAX_EXECUTION_TIMEOUT_SECONDS", value)
		if _, err := LoadConfigFromEnv(testRedisURL); err == nil {
			t.Fatalf("SANDBOX_MAX_EXECUTION_TIMEOUT_SECONDS=%q unexpectedly resolved", value)
		}
	}
}

func TestLoadConfigRequiresRedisURL(t *testing.T) {
	t.Setenv("SANDBOX_EXECUTION_RECORD_TTL", "1h")
	if _, err := LoadConfigFromEnv(""); err == nil {
		t.Fatal("missing Redis URL unexpectedly resolved")
	}
}

// The store must not re-introduce a retention default of its own.
func TestNewRedisStoreRejectsNonPositiveTTL(t *testing.T) {
	policy := testExecutionPolicy(testMaxExecutionTimeoutSeconds)
	if _, err := NewRedisStore(testRedisURL, "agentarea:test", 0, policy); err == nil {
		t.Fatal("zero TTL unexpectedly accepted")
	}
	if _, err := NewRedisStore(testRedisURL, "agentarea:test", -time.Second, policy); err == nil {
		t.Fatal("negative TTL unexpectedly accepted")
	}
}

func TestLoadConfigRejectsMissingExecutionAdmissionPolicy(t *testing.T) {
	t.Setenv("SANDBOX_EXECUTION_RECORD_TTL", "1h")
	t.Setenv("SANDBOX_MAX_EXECUTION_TIMEOUT_SECONDS", "1800")
	for _, missing := range []string{
		"SANDBOX_DEFAULT_EXECUTION_TIMEOUT_SECONDS",
		"SANDBOX_EXECUTION_QUEUE_TIMEOUT",
		"SANDBOX_EXECUTION_COMPLETION_GRACE",
	} {
		t.Run(missing, func(t *testing.T) {
			t.Setenv("SANDBOX_DEFAULT_EXECUTION_TIMEOUT_SECONDS", "120")
			t.Setenv("SANDBOX_EXECUTION_QUEUE_TIMEOUT", "5m")
			t.Setenv("SANDBOX_EXECUTION_COMPLETION_GRACE", "1m")
			t.Setenv(missing, "")
			if _, err := LoadConfigFromEnv(testRedisURL); err == nil {
				t.Fatalf("missing %s unexpectedly resolved", missing)
			}
		})
	}
}
