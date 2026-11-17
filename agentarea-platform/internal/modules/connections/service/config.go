package service

// Config is what the module reads from the environment (connections.LoadConfig).
type Config struct {
	HydraURL        string
	HydraAdminURL   string
	HydraBrowserURL string
	// OAuthScopes is AGENTAREA_MCP_OAUTH_SCOPES split on whitespace.
	OAuthScopes []string
	// OAuthApps are the operator's registered OAuth apps, one per issuer.
	OAuthApps []OAuthApp
	// GatewaySecret derives the per-instance context-signing key; empty: unset.
	GatewaySecret string
}

// OAuthApp is one entry of AGENTAREA_MCP_OAUTH_APPS (MCPOAuthApp).
type OAuthApp struct {
	Issuer                string   `json:"issuer"`
	ClientID              string   `json:"client_id"`
	ClientSecret          string   `json:"client_secret"`
	AuthorizationEndpoint string   `json:"authorization_endpoint"`
	TokenEndpoint         string   `json:"token_endpoint"`
	ResourceOrigins       []string `json:"resource_origins"`
}

// App is the platform app registered for issuer; nil when none.
func (c Config) App(issuer string) *OAuthApp {
	for i := range c.OAuthApps {
		if c.OAuthApps[i].Issuer == issuer {
			return &c.OAuthApps[i]
		}
	}
	return nil
}
