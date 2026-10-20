package config

import (
	"strings"
	"testing"
	"time"
)

func TestLoadReadsAgentareaEventsEnv(t *testing.T) {
	setRequired(t)
	t.Setenv("AGENTAREA_DB_HOST", "localhost")
	t.Setenv("AGENTAREA_DB_PORT", "5432")
	t.Setenv("AGENTAREA_DB_NAME", "agentarea")
	t.Setenv("AGENTAREA_DB_USER", "agentarea")
	t.Setenv("AGENTAREA_DB_PASSWORD", "test")
	t.Setenv("AGENTAREA_REDIS_URL", "redis://localhost:6379/0")
	t.Setenv("AGENTAREA_EVENT_WORKER_ID", "worker-test")
	t.Setenv("AGENTAREA_EVENT_POLL_INTERVAL", "17s")
	t.Setenv("AGENTAREA_EVENT_MAX_POLLERS", "7")
	t.Setenv("AGENTAREA_EVENT_NAMESPACE", "staging")
	t.Setenv("AGENTAREA_API_URL", "https://api.example.com/")
	t.Setenv("AGENTAREA_HTTP_ALLOW_PRIVATE", "true")
	t.Setenv("AGENTAREA_HTTP_PRIVATE_ALLOWLIST", "localhost, 10.0.0.0/8")
	t.Setenv("PORT", "18002")
	t.Setenv("AGENTAREA_OTEL_ENABLED", "true")

	cfg := mustLoad(t)

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
	if cfg.Namespace != "staging" {
		t.Fatalf("Namespace = %q", cfg.Namespace)
	}
	if cfg.APIURL != "https://api.example.com" {
		t.Fatalf("APIURL = %q", cfg.APIURL)
	}
	if !cfg.Egress.AllowPrivate || len(cfg.Egress.PrivateAllowlist) != 2 || cfg.Egress.PrivateAllowlist[1] != "10.0.0.0/8" {
		t.Fatalf("Egress = %+v", cfg.Egress)
	}
	if cfg.Port != "18002" {
		t.Fatalf("Port = %q", cfg.Port)
	}
	if !cfg.OTelEnabled {
		t.Fatal("OTelEnabled = false")
	}
}

func TestLoadLeavesTracingOffByDefault(t *testing.T) {
	setRequired(t)
	t.Setenv("AGENTAREA_OTEL_ENABLED", "")

	if cfg := mustLoad(t); cfg.OTelEnabled {
		t.Fatal("OTelEnabled = true without AGENTAREA_OTEL_ENABLED")
	}
}

func TestLoadRejectsUnparsableOTelEnabled(t *testing.T) {
	setRequired(t)
	t.Setenv("AGENTAREA_OTEL_ENABLED", "yes please")

	if _, err := Load(); err == nil {
		t.Fatal("Load accepted AGENTAREA_OTEL_ENABLED=\"yes please\"")
	}
}

func TestLoadRequiresTheAPIURL(t *testing.T) {
	setRequired(t)
	t.Setenv("AGENTAREA_API_URL", "")

	if _, err := Load(); err == nil || !strings.Contains(err.Error(), "AGENTAREA_API_URL") {
		t.Fatalf("err = %v, want one naming AGENTAREA_API_URL", err)
	}
}

func TestLoadRequiresTheSecretKey(t *testing.T) {
	setRequired(t)
	t.Setenv("AGENTAREA_SECRET_ENCRYPTION_KEY", "")

	if _, err := Load(); err == nil || !strings.Contains(err.Error(), "AGENTAREA_SECRET_ENCRYPTION_KEY") {
		t.Fatalf("err = %v, want one naming AGENTAREA_SECRET_ENCRYPTION_KEY", err)
	}
}

func TestLoadRefusesASecretBackendItCannotRead(t *testing.T) {
	setRequired(t)
	t.Setenv("AGENTAREA_SECRET_BACKEND", "infisical")

	if _, err := Load(); err == nil {
		t.Fatal("Load accepted a secret backend the event service cannot read")
	}
}

func TestLoadRejectsUnparsableAllowPrivate(t *testing.T) {
	setRequired(t)
	t.Setenv("AGENTAREA_HTTP_ALLOW_PRIVATE", "sometimes")

	if _, err := Load(); err == nil {
		t.Fatal("Load accepted AGENTAREA_HTTP_ALLOW_PRIVATE=\"sometimes\"")
	}
}

func setRequired(t *testing.T) {
	t.Helper()
	t.Setenv("AGENTAREA_API_URL", "https://api.example.com")
	t.Setenv("AGENTAREA_SECRET_ENCRYPTION_KEY", "a2V5")
	t.Setenv("AGENTAREA_SECRET_BACKEND", "")
	t.Setenv("AGENTAREA_HTTP_ALLOW_PRIVATE", "")
	t.Setenv("AGENTAREA_HTTP_PRIVATE_ALLOWLIST", "")
	t.Setenv("AGENTAREA_MCP_MANAGER_URL", "http://mcp-manager:80/")
	t.Setenv("AGENTAREA_MCP_GATEWAY_SECRET", strings.Repeat("g", 32))
}

func TestLoadReadsTheMCPGateway(t *testing.T) {
	setRequired(t)
	cfg := mustLoad(t)
	if cfg.MCPManagerURL != "http://mcp-manager:80" || cfg.MCPGatewaySecret != strings.Repeat("g", 32) {
		t.Fatalf("gateway = %q / %d bytes", cfg.MCPManagerURL, len(cfg.MCPGatewaySecret))
	}
}

func TestLoadRefusesToStartWithoutTheMCPGateway(t *testing.T) {
	for name, env := range map[string][2]string{
		"no manager url": {"AGENTAREA_MCP_MANAGER_URL", ""},
		"no secret":      {"AGENTAREA_MCP_GATEWAY_SECRET", ""},
		"short secret":   {"AGENTAREA_MCP_GATEWAY_SECRET", "short"},
	} {
		setRequired(t)
		t.Setenv(env[0], env[1])
		if _, err := Load(); err == nil || !strings.Contains(err.Error(), env[0]) {
			t.Fatalf("%s: err = %v", name, err)
		}
	}
}

func mustLoad(t *testing.T) *Config {
	t.Helper()
	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}
	return cfg
}

func TestLoadBuildsEscapedDatabaseConnStringFromComponentEnvs(t *testing.T) {
	setRequired(t)
	t.Setenv("AGENTAREA_DB_HOST", "agentarea-postgresql")
	t.Setenv("AGENTAREA_DB_PORT", "5432")
	t.Setenv("AGENTAREA_DB_NAME", "agentarea")
	t.Setenv("AGENTAREA_DB_USER", "agentarea")
	t.Setenv("AGENTAREA_DB_PASSWORD", "p@ss/with:chars")
	t.Setenv("AGENTAREA_DB_SSLMODE", "disable")

	cfg := mustLoad(t)

	if cfg.DatabaseURL != "host='agentarea-postgresql' port='5432' user='agentarea' password='p@ss/with:chars' dbname='agentarea' sslmode='disable'" {
		t.Fatalf("DatabaseURL = %q", cfg.DatabaseURL)
	}
}

func TestLoadLeavesDatabaseUnsetWithoutCredentials(t *testing.T) {
	setRequired(t)
	t.Setenv("AGENTAREA_DB_HOST", "agentarea-postgresql")
	t.Setenv("AGENTAREA_DB_NAME", "agentarea")
	t.Setenv("AGENTAREA_DB_USER", "")
	t.Setenv("AGENTAREA_DB_PASSWORD", "")

	if cfg := mustLoad(t); cfg.DatabaseURL != "" {
		t.Fatalf("DatabaseURL = %q, want empty so startup refuses to run", cfg.DatabaseURL)
	}
}

func TestLoadEscapesPostgresConnStringValues(t *testing.T) {
	setRequired(t)
	t.Setenv("AGENTAREA_DB_HOST", "agentarea-postgresql")
	t.Setenv("AGENTAREA_DB_PORT", "5432")
	t.Setenv("AGENTAREA_DB_NAME", "agentarea")
	t.Setenv("AGENTAREA_DB_USER", "agent'area")
	t.Setenv("AGENTAREA_DB_PASSWORD", `p\ass'word`)

	cfg := mustLoad(t)

	if cfg.DatabaseURL != `host='agentarea-postgresql' port='5432' user='agent\'area' password='p\\ass\'word' dbname='agentarea' sslmode='disable'` {
		t.Fatalf("DatabaseURL = %q", cfg.DatabaseURL)
	}
}
