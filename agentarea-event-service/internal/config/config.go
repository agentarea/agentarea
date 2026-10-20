package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

// Config holds all configuration for the Event Service.
type Config struct {
	DatabaseURL string
	RedisURL    string
	WorkerID    string
	Namespace   string
	// PollInterval is how often the set of sources is read again; each source
	// polls at the interval its catalog entry names.
	PollInterval time.Duration
	MaxPollers   int
	Port         string
	OTelEnabled  bool
	// APIURL is the public base of the API: a source's webhook URL is
	// {APIURL}/webhooks/{webhook_id}, the address registration hands a provider.
	APIURL string
	// SecretKey is the Fernet key the database secret backend encrypts with.
	SecretKey string
	Egress    Egress
	// MCPManagerURL and MCPGatewaySecret reach a member's MCP server through
	// the mcp-manager gateway, which holds its credentials (MCP Events).
	MCPManagerURL    string
	MCPGatewaySecret string
}

// Egress is the outbound policy for hosts a member names (a feed URL, a
// mailbox): only public addresses unless the operator opens private ones.
type Egress struct {
	AllowPrivate     bool
	PrivateAllowlist []string
}

const (
	otelEnabledEnv       = "AGENTAREA_OTEL_ENABLED"
	apiURLEnv            = "AGENTAREA_API_URL"
	secretBackendEnv     = "AGENTAREA_SECRET_BACKEND"
	secretKeyEnv         = "AGENTAREA_SECRET_ENCRYPTION_KEY"
	allowPrivateEnv      = "AGENTAREA_HTTP_ALLOW_PRIVATE"
	privateAllowlistEnv  = "AGENTAREA_HTTP_PRIVATE_ALLOWLIST"
	mcpManagerURLEnv     = "AGENTAREA_MCP_MANAGER_URL"
	mcpGatewaySecretEnv  = "AGENTAREA_MCP_GATEWAY_SECRET" // pragma: allowlist secret
	supportedSecretStore = "database"
)

// Load reads configuration from environment variables with sensible defaults.
func Load() (*Config, error) {
	workerID := os.Getenv("AGENTAREA_EVENT_WORKER_ID")
	if workerID == "" {
		if hostname, err := os.Hostname(); err == nil {
			workerID = hostname
		} else {
			workerID = "event-service-worker"
		}
	}

	pollInterval := 5 * time.Second
	if v := os.Getenv("AGENTAREA_EVENT_POLL_INTERVAL"); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			pollInterval = d
		}
	}

	maxPollers := 200
	if v := os.Getenv("AGENTAREA_EVENT_MAX_POLLERS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			maxPollers = n
		}
	}

	namespace := os.Getenv("AGENTAREA_EVENT_NAMESPACE")
	if namespace == "" {
		namespace = "agentarea"
	}

	otelEnabled := false
	if v := os.Getenv(otelEnabledEnv); v != "" {
		parsed, err := strconv.ParseBool(v)
		if err != nil {
			return nil, fmt.Errorf("%s=%q is not a boolean: %w", otelEnabledEnv, v, err)
		}
		otelEnabled = parsed
	}

	port := os.Getenv("PORT")
	if port == "" {
		port = "8002"
	}

	apiURL := strings.TrimRight(os.Getenv(apiURLEnv), "/")
	if apiURL == "" {
		return nil, fmt.Errorf("%s is required: it is the public base of the webhook URLs sources register", apiURLEnv)
	}

	if backend := os.Getenv(secretBackendEnv); backend != "" && backend != supportedSecretStore {
		return nil, fmt.Errorf("%s=%q: the event service reads source credentials from the %q backend only", secretBackendEnv, backend, supportedSecretStore)
	}
	secretKey := os.Getenv(secretKeyEnv)
	if secretKey == "" {
		return nil, fmt.Errorf("%s is required: source credentials are encrypted with it", secretKeyEnv)
	}

	mcpManagerURL := strings.TrimRight(os.Getenv(mcpManagerURLEnv), "/")
	if mcpManagerURL == "" {
		return nil, fmt.Errorf("%s is required: MCP Events sources are polled and subscribed through the mcp-manager gateway", mcpManagerURLEnv)
	}
	mcpGatewaySecret := os.Getenv(mcpGatewaySecretEnv)
	if len(mcpGatewaySecret) < 32 {
		return nil, fmt.Errorf("%s is required and must contain at least 32 bytes: it authorizes calls to the mcp-manager gateway", mcpGatewaySecretEnv)
	}

	egress := Egress{}
	if v := os.Getenv(allowPrivateEnv); v != "" {
		parsed, err := strconv.ParseBool(v)
		if err != nil {
			return nil, fmt.Errorf("%s=%q is not a boolean: %w", allowPrivateEnv, v, err)
		}
		egress.AllowPrivate = parsed
	}
	for _, entry := range strings.Split(os.Getenv(privateAllowlistEnv), ",") {
		if entry = strings.TrimSpace(entry); entry != "" {
			egress.PrivateAllowlist = append(egress.PrivateAllowlist, entry)
		}
	}

	return &Config{
		DatabaseURL:  databaseURL(),
		RedisURL:     os.Getenv("AGENTAREA_REDIS_URL"),
		WorkerID:     workerID,
		Namespace:    namespace,
		PollInterval: pollInterval,
		MaxPollers:   maxPollers,
		Port:         port,
		OTelEnabled:  otelEnabled,
		APIURL:       apiURL,
		SecretKey:    secretKey,
		Egress:       egress,

		MCPManagerURL:    mcpManagerURL,
		MCPGatewaySecret: mcpGatewaySecret,
	}, nil
}

func databaseURL() string {
	host := os.Getenv("AGENTAREA_DB_HOST")
	port := os.Getenv("AGENTAREA_DB_PORT")
	db := os.Getenv("AGENTAREA_DB_NAME")
	user := os.Getenv("AGENTAREA_DB_USER")
	password := os.Getenv("AGENTAREA_DB_PASSWORD")
	if host == "" || db == "" || user == "" || password == "" {
		return ""
	}

	sslMode := os.Getenv("AGENTAREA_DB_SSLMODE")
	if sslMode == "" {
		sslMode = "disable"
	}

	return fmt.Sprintf(
		"host=%s port=%s user=%s password=%s dbname=%s sslmode=%s",
		pqConnValue(host),
		pqConnValue(port),
		pqConnValue(user),
		pqConnValue(password),
		pqConnValue(db),
		pqConnValue(sslMode),
	)
}

func pqConnValue(value string) string {
	escaped := strings.ReplaceAll(value, `\`, `\\`)
	escaped = strings.ReplaceAll(escaped, `'`, `\'`)
	return "'" + escaped + "'"
}
