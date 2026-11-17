package service

import (
	"net/url"
	"strings"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/analytics"
)

// publicIssuerHosts is PUBLIC_ISSUER_HOSTS: the authorization servers analytics may name.
func publicIssuerHosts() map[string]bool {
	return map[string]bool{
		"accounts.google.com": true, "api.notion.com": true, "auth.atlassian.com": true, "github.com": true,
		"gitlab.com": true, "linear.app": true, "login.microsoftonline.com": true, "login.salesforce.com": true,
		"oauth.yandex.ru": true, "slack.com": true, "www.canva.com": true, "www.figma.com": true,
	}
}

// oauthErrorCodes is OAUTH_ERROR_CODES: RFC 6749 §4.1.2.1 and §5.2.
func oauthErrorCodes() map[string]bool {
	return map[string]bool{
		"invalid_request": true, "unauthorized_client": true, "access_denied": true, "unsupported_response_type": true,
		"invalid_scope": true, "server_error": true, "temporarily_unavailable": true, "invalid_client": true,
		"invalid_grant": true, "unsupported_grant_type": true,
	}
}

// oauthProvider is _provider_label: the issuer's host when a platform app serves it and it is public.
func (s *Service) oauthProvider(issuer string) string {
	if issuer == "" || s.d.Config.App(oaNormalizeIssuer(issuer)) == nil {
		return "custom"
	}
	u, err := url.Parse(issuer)
	if err != nil {
		return "custom"
	}
	if host := strings.ToLower(u.Hostname()); publicIssuerHosts()[host] {
		return host
	}
	return "custom"
}

// oauthErrorLabel is _oauth_error.
func oauthErrorLabel(code string) string {
	if oauthErrorCodes()[code] {
		return code
	}
	return "other"
}

// oauthFailure is the provider's error code as _oauth_error labels it, or why there is none.
func oauthFailure(code, without string) string {
	if code == "" {
		return without
	}
	return oauthErrorLabel(code)
}

// authConfigIssuer is _auth_config_issuer.
func authConfigIssuer(cfg map[string]any) string {
	return oaFirstNonEmpty(oaPyStr(cfg["platform_oauth_issuer"]), oaPyStr(cfg["issuer"]))
}

func (s *Service) countOAuth(provider, outcome string) {
	analytics.Count(s.d.Counter, "oauth_connect", map[string]string{"provider": provider, "outcome": outcome})
}
