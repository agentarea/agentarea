package connections

import (
	"encoding/json"
	"errors"
	"net/url"
	"strconv"
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
		return nil, errors.New("must be a JSON list of {issuer, client_id, client_secret, authorization_endpoint, token_endpoint, resource_origins, install_url, app_id, private_key, api_url}")
	}
	seen := map[string]bool{}
	var dup []string
	for i := range apps {
		a := &apps[i]
		if a.Issuer == "" || a.ClientID == "" || a.ClientSecret == "" || a.AuthorizationEndpoint == "" || a.TokenEndpoint == "" {
			return nil, errors.New("every app needs issuer, client_id, client_secret, authorization_endpoint and token_endpoint")
		}
		if a.InstallURL != "" {
			if u, err := url.Parse(a.InstallURL); err != nil || u.Scheme != "https" || u.Host == "" {
				return nil, errors.New("install_url of " + a.Issuer + " must be an https URL")
			}
		}
		if err := checkInstallationTokens(a); err != nil {
			return nil, err
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

// checkInstallationTokens validates app_id, private_key and api_url, all three
// or none, and parses the key; its errors never quote the key.
func checkInstallationTokens(a *service.OAuthApp) error {
	set := 0
	for _, v := range []string{a.AppID.String(), a.PrivateKey, a.APIURL} {
		if v != "" {
			set++
		}
	}
	if set == 0 {
		return nil
	}
	if set != 3 {
		return errors.New(a.Issuer + " needs all of app_id, private_key and api_url, or none")
	}
	if n, err := strconv.ParseInt(a.AppID.String(), 10, 64); err != nil || n <= 0 {
		return errors.New("app_id of " + a.Issuer + " must be a positive integer")
	}
	a.APIURL = strings.TrimRight(a.APIURL, "/")
	if u, err := url.Parse(a.APIURL); err != nil || u.Scheme != "https" || u.Host == "" {
		return errors.New("api_url of " + a.Issuer + " must be an https URL")
	}
	key, err := service.ParseInstallationKey(a.PrivateKey)
	if err != nil {
		return errors.New("private_key of " + a.Issuer + " " + err.Error())
	}
	a.InstallationKey = key
	return nil
}
