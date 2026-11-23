package service

import (
	"crypto/rsa"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"errors"
)

// Config is what the module reads from the environment (connections.LoadConfig).
type Config struct {
	HydraURL      string
	HydraAdminURL string
	// KratosAdminURL is where a consent reads the user's traits for the
	// email and profile claims.
	KratosAdminURL  string
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
	// InstallURL is where a user picks what the app may reach (a GitHub
	// App's installations/new page); empty when the app has none.
	InstallURL string `json:"install_url,omitempty"`
	// AppID, PrivateKey (PEM) and APIURL make the app a GitHub App whose
	// connections can be bound to one installation: a bound connection sends
	// an installation access token, not the user's. All three or none.
	AppID      json.Number `json:"app_id,omitempty"`
	PrivateKey string      `json:"private_key,omitempty"`
	APIURL     string      `json:"api_url,omitempty"`
	// InstallationKey is PrivateKey parsed at startup; nil when unset.
	InstallationKey *rsa.PrivateKey `json:"-"`
}

// MintsInstallationTokens reports an app that can mint installation access tokens.
func (a *OAuthApp) MintsInstallationTokens() bool {
	return a != nil && a.InstallationKey != nil && a.AppID != "" && a.APIURL != ""
}

// ParseInstallationKey reads a GitHub App's PEM private key (PKCS#1 or PKCS#8 RSA).
func ParseInstallationKey(raw string) (*rsa.PrivateKey, error) {
	block, _ := pem.Decode([]byte(raw))
	if block == nil {
		return nil, errors.New("is not a PEM block")
	}
	if k, err := x509.ParsePKCS1PrivateKey(block.Bytes); err == nil {
		return k, nil
	}
	k, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		return nil, errors.New("is not an RSA private key")
	}
	rk, ok := k.(*rsa.PrivateKey)
	if !ok {
		return nil, errors.New("is not an RSA private key")
	}
	return rk, nil
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
