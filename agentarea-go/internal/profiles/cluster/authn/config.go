package authn

import (
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strings"
	"unicode/utf8"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
)

// Config is what authentication reads (config/auth.py AuthSettings, the
// gateway secret of config/mcp.py, API_URL of config/app.py).
type Config struct {
	// JWKSB64 is Kratos's JWKS, base64 or raw JSON. Empty is allowed, as in
	// Python: every token Kratos would judge then fails as an internal error
	// unless Hydra accepts it.
	JWKSB64  string
	Issuer   string
	Audience string
	// HydraURL is where Hydra's JWKS is fetched from.
	HydraURL string
	// HydraAudience is the audience Hydra tokens must carry; empty refuses
	// every Hydra token.
	HydraAudience string
	// APIURL is the public API URL in the 401 challenge.
	APIURL string
	// GatewaySecret derives the turn-token key; empty disables turn tokens.
	GatewaySecret string
}

// publishedSecrets are values committed to the repository (config/mcp.py
// PUBLISHED_SECRET_VALUES); a deployment using one is refused.
func publishedSecrets() []string {
	return []string{
		"dev-sandbox-activation-hmac-secret-change-in-prod",
		"dev-sandbox-cleanup-hmac-secret-change-in-prod-00",
		"dev-sandbox-file-auth-secret-change-in-prod-000000",
		"dev-sandbox-control-auth-secret-change-in-prod-0000",
		"dev-mcp-gateway-auth-secret-change-in-prod-00000000",
		"agentarea-dev-sandbox-activation-secret-change-me",
		"agentarea-dev-sandbox-cleanup-secret-change-me",
		"agentarea-dev-sandbox-file-secret-change-me",
		"agentarea-dev-sandbox-control-secret-change-me",
		"agentarea-dev-mcp-gateway-secret-change-me",
	}
}

// LoadConfig reads Config with Python's defaults.
func LoadConfig(l *config.Loader) Config {
	c := Config{
		JWKSB64:  l.StringEnv("AGENTAREA_AUTH_JWKS_B64", ""),
		Issuer:   l.StringEnv("AGENTAREA_AUTH_ISSUER", "http://localhost:4433"),
		Audience: l.StringEnv("AGENTAREA_AUTH_AUDIENCE", "agentarea-api"),
		HydraURL: l.StringEnv("AGENTAREA_AUTH_HYDRA_URL", "http://hydra:4444"),
		APIURL:   l.StringEnv("AGENTAREA_API_URL", "http://localhost:8000"),
	}
	if err := checkHydraURL(c.HydraURL); err != nil {
		l.Fail("AGENTAREA_AUTH_HYDRA_URL", err)
	}
	c.HydraAudience, _ = l.OptionalEnv("AGENTAREA_AUTH_HYDRA_AUDIENCE")
	c.GatewaySecret, _ = l.OptionalEnv("AGENTAREA_MCP_GATEWAY_SECRET")
	if c.GatewaySecret != "" {
		if slices.Contains(publishedSecrets(), c.GatewaySecret) {
			l.Fail("AGENTAREA_MCP_GATEWAY_SECRET", errors.New("is set to a value published in the AgentArea repository; generate a new one (scripts/gen-dev-secrets.sh rotates it) and restart"))
		}
		if utf8.RuneCountInString(c.GatewaySecret) < 32 {
			l.Fail("AGENTAREA_MCP_GATEWAY_SECRET", errors.New("must contain at least 32 bytes"))
		}
	}
	return c
}

// checkHydraURL refuses at startup what PyJWKClient refuses on every request:
// a JWKS URL that is not http or https.
func checkHydraURL(raw string) error {
	u, err := url.Parse(raw)
	if err != nil {
		return errors.New("is not a URL")
	}
	if scheme := strings.ToLower(u.Scheme); scheme != "http" && scheme != "https" {
		return fmt.Errorf("has scheme %q: only 'http' and 'https' are supported", scheme)
	}
	return nil
}
