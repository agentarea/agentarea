package config

import (
	"testing"
	"time"
)

func TestLoadReadsAgentareaEventsEnv(t *testing.T) {
	t.Setenv("AGENTAREA_DB_HOST", "localhost")
	t.Setenv("AGENTAREA_DB_PORT", "5432")
	t.Setenv("AGENTAREA_DB_NAME", "agentarea")
	t.Setenv("AGENTAREA_DB_USER", "agentarea")
	t.Setenv("AGENTAREA_DB_PASSWORD", "test")
	t.Setenv("AGENTAREA_REDIS_URL", "redis://localhost:6379/0")
	t.Setenv("AGENTAREA_EVENT_WORKER_ID", "worker-test")
	t.Setenv("AGENTAREA_EVENT_POLL_INTERVAL", "17s")
	t.Setenv("AGENTAREA_EVENT_MAX_POLLERS", "7")
	t.Setenv("AGENTAREA_EVENT_STREAM", "events.inbound.test")
	t.Setenv("AGENTAREA_EVENT_TELEGRAM_ENABLED", "true")
	t.Setenv("PORT", "18002")

	cfg := Load()

	if cfg.DatabaseURL != "host='localhost' port='5432' user='agentarea' password='test' dbname='agentarea' sslmode='disable'" { // pragma: allowlist secret
		t.Fatalf("DatabaseURL = %q", cfg.DatabaseURL)
	}
	if cfg.RedisURL != "redis://localhost:6379/0" {
		t.Fatalf("RedisURL = %q", cfg.RedisURL)
	}
	if cfg.WorkerID != "worker-test" {
		t.Fatalf("WorkerID = %q", cfg.WorkerID)
	}
	if cfg.PollInterval != 17*time.Second {
		t.Fatalf("PollInterval = %s", cfg.PollInterval)
	}
	if cfg.MaxPollers != 7 {
		t.Fatalf("MaxPollers = %d", cfg.MaxPollers)
	}
	if cfg.InboundStream != "events.inbound.test" {
		t.Fatalf("InboundStream = %q", cfg.InboundStream)
	}
	if !cfg.EnableTelegramPolling {
		t.Fatal("EnableTelegramPolling = false")
	}
	if cfg.Port != "18002" {
		t.Fatalf("Port = %q", cfg.Port)
	}
}

func TestLoadBuildsEscapedDatabaseConnStringFromComponentEnvs(t *testing.T) {
	t.Setenv("AGENTAREA_DB_HOST", "agentarea-postgresql")
	t.Setenv("AGENTAREA_DB_PORT", "5432")
	t.Setenv("AGENTAREA_DB_NAME", "agentarea")
	t.Setenv("AGENTAREA_DB_USER", "agentarea")
	t.Setenv("AGENTAREA_DB_PASSWORD", "p@ss/with:chars")
	t.Setenv("AGENTAREA_DB_SSLMODE", "disable")

	cfg := Load()

	if cfg.DatabaseURL != "host='agentarea-postgresql' port='5432' user='agentarea' password='p@ss/with:chars' dbname='agentarea' sslmode='disable'" {
		t.Fatalf("DatabaseURL = %q", cfg.DatabaseURL)
	}
}

func TestLoadLeavesDatabaseUnsetWithoutCredentials(t *testing.T) {
	t.Setenv("AGENTAREA_DB_HOST", "agentarea-postgresql")
	t.Setenv("AGENTAREA_DB_NAME", "agentarea")
	t.Setenv("AGENTAREA_DB_USER", "")
	t.Setenv("AGENTAREA_DB_PASSWORD", "")

	if cfg := Load(); cfg.DatabaseURL != "" {
		t.Fatalf("DatabaseURL = %q, want empty so startup refuses to run", cfg.DatabaseURL)
	}
}

func TestLoadEscapesPostgresConnStringValues(t *testing.T) {
	t.Setenv("AGENTAREA_DB_HOST", "agentarea-postgresql")
	t.Setenv("AGENTAREA_DB_PORT", "5432")
	t.Setenv("AGENTAREA_DB_NAME", "agentarea")
	t.Setenv("AGENTAREA_DB_USER", "agent'area")
	t.Setenv("AGENTAREA_DB_PASSWORD", `p\ass'word`)

	cfg := Load()

	if cfg.DatabaseURL != `host='agentarea-postgresql' port='5432' user='agent\'area' password='p\\ass\'word' dbname='agentarea' sslmode='disable'` {
		t.Fatalf("DatabaseURL = %q", cfg.DatabaseURL)
	}
}
