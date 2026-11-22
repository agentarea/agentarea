package connections

import (
	"encoding/json"
	"errors"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/service"
)

// Config is MCPSettings and the Hydra half of AuthSettings that connections reads.
type Config = service.Config

// LoadConfig reads the module's settings. The gateway secret's own checks
// (length, published values) are the authn profile's; an unset secret leaves
// context signing for container instances off.
func LoadConfig(l *config.Loader) Config {
	c := Config{
		HydraURL:        l.StringEnv("AGENTAREA_AUTH_HYDRA_URL", "http://hydra:4444"),
		HydraAdminURL:   l.StringEnv("AGENTAREA_AUTH_HYDRA_ADMIN_URL", "http://hydra:4445"),
		HydraBrowserURL: l.StringEnv("AGENTAREA_AUTH_HYDRA_BROWSER_URL", "http://localhost:4444"),
		OAuthScopes:     strings.Fields(l.StringEnv("AGENTAREA_MCP_OAUTH_SCOPES", "openid offline_access offline email profile")),
	}
	c.GatewaySecret, _ = l.OptionalEnv("AGENTAREA_MCP_GATEWAY_SECRET")
	if raw, ok := l.OptionalEnv("AGENTAREA_MCP_OAUTH_APPS"); ok {
		apps, err := parseOAuthApps(raw)
		if err != nil {
			l.Fail("AGENTAREA_MCP_OAUTH_APPS", err)
		}
		c.OAuthApps = apps
	}
	return c
}

// parseOAuthApps reads AGENTAREA_MCP_OAUTH_APPS without echoing its secrets.
func parseOAuthApps(raw string) ([]service.OAuthApp, error) {
	var apps []service.OAuthApp
	if err := json.Unmarshal([]byte(raw), &apps); err != nil {
		return nil, errors.New("must be a JSON list of {issuer, client_id, client_secret, authorization_endpoint, token_endpoint, resource_origins}")
	}
	seen := map[string]bool{}
	var dup []string
	for _, a := range apps {
		if a.Issuer == "" || a.ClientID == "" || a.ClientSecret == "" || a.AuthorizationEndpoint == "" || a.TokenEndpoint == "" {
			return nil, errors.New("every app needs issuer, client_id, client_secret, authorization_endpoint and token_endpoint")
		}
		if seen[a.Issuer] {
			dup = append(dup, a.Issuer)
		}
		seen[a.Issuer] = true
	}
	if len(dup) > 0 {
		return nil, errors.New("lists " + strings.Join(dup, ", ") + " twice")
	}
	return apps, nil
}
