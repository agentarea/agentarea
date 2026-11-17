package secrets

import (
	"errors"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
)

// Backend names, as AGENTAREA_SECRET_BACKEND spells them.
const (
	BackendDatabase  = "database"
	BackendInfisical = "infisical"
)

// DefaultInfisicalEndpoint is where Python points when AGENTAREA_SECRET_ENDPOINT is unset.
const DefaultInfisicalEndpoint = "https://app.infisical.com"

// Config is AGENTAREA_SECRET_* (config/secrets.py SecretManagerSettings).
type Config struct {
	Backend string
	// EncryptionKey is the Fernet key; required, and checked, for the database backend.
	EncryptionKey string
	// The rest is read for the Infisical backend only.
	Endpoint     string
	ClientID     string
	ClientSecret string
	ProjectID    string
	Env          string
}

// LoadConfig reads Config and validates it as SecretManagerFactory does at
// construction, with the same messages. Unlike Python, an unknown backend
// fails here instead of at first use, and the Fernet key is parsed here.
func LoadConfig(l *config.Loader) Config {
	c := Config{
		Backend:       strings.ToLower(l.StringEnv("AGENTAREA_SECRET_BACKEND", BackendDatabase)),
		EncryptionKey: l.StringEnv("AGENTAREA_SECRET_ENCRYPTION_KEY", ""),
		Endpoint:      l.StringEnv("AGENTAREA_SECRET_ENDPOINT", ""),
		ClientID:      l.StringEnv("AGENTAREA_SECRET_CLIENT_ID", ""),
		ClientSecret:  l.StringEnv("AGENTAREA_SECRET_CLIENT_SECRET", ""),
		ProjectID:     l.StringEnv("AGENTAREA_SECRET_PROJECT_ID", ""),
		Env:           l.StringEnv("AGENTAREA_SECRET_ENV", "prod"),
	}
	switch c.Backend {
	case BackendDatabase:
		if c.EncryptionKey == "" {
			l.Fail("AGENTAREA_SECRET_ENCRYPTION_KEY", errors.New("must be set when using the database secret manager; generate one with: openssl rand -base64 32 | tr '+/' '-_'"))
		} else if err := ParseFernetKey(c.EncryptionKey); err != nil {
			l.Fail("AGENTAREA_SECRET_ENCRYPTION_KEY", err)
		}
	case BackendInfisical:
		if c.ClientID == "" || c.ClientSecret == "" {
			l.Fail("AGENTAREA_SECRET_CLIENT_ID", errors.New("Infisical credentials not configured; set AGENTAREA_SECRET_CLIENT_ID and AGENTAREA_SECRET_CLIENT_SECRET")) //nolint:staticcheck
		}
		if c.ProjectID == "" {
			l.Fail("AGENTAREA_SECRET_PROJECT_ID", errors.New("must be set when using the Infisical secret manager: it selects which Infisical project holds the secrets"))
		}
		if c.Endpoint == "" {
			c.Endpoint = DefaultInfisicalEndpoint
		}
	default:
		l.Fail("AGENTAREA_SECRET_BACKEND", errors.New("must be database or infisical, got "+c.Backend))
	}
	return c
}
