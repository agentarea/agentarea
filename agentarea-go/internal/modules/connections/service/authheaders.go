package service

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
)

// PlatformWorkspaceID is PLATFORM_WORKSPACE_ID: platform-managed connections
// keep their auth configs and credentials there.
const PlatformWorkspaceID = "platform"

// PlatformWorkspace is the workspace whose auth configs a platform-managed
// connection signs in with, whichever workspace calls it.
func PlatformWorkspace() scope.Workspace {
	ws, err := scope.NewWorkspace(PlatformWorkspaceID, PlatformWorkspaceID)
	if err != nil {
		panic(err)
	}
	return ws
}

// AuthHeaders is MCPAuthService.get_auth_headers_for: the headers the auth
// config id of ws adds to a request to destination (an absolute URL),
// refreshing an OAuth token that expires within 30 s or when forceRefresh.
// A platform-managed connection passes PlatformWorkspace() as ws.
// *domain.ReauthRequired when the session cannot be renewed unattended;
// *domain.Invalid for a config ws does not have, missing credentials, or
// managed credentials asked for another origin.
func (s *Service) AuthHeaders(ctx context.Context, ws scope.Workspace, authConfigID uuid.UUID, destination string, forceRefresh bool) (map[string]string, error) {
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return nil, err
	}
	a, ok, err := s.d.Auth.Get(ctx, sess, authConfigID)
	if err != nil {
		release()
		return nil, err
	}
	if !ok {
		release()
		return nil, &domain.Invalid{Msg: fmt.Sprintf("Auth config %s not found in this workspace", authConfigID)}
	}
	if domain.IsManaged(a.Config) {
		app, err := s.platformApp(a)
		if err != nil {
			release()
			return nil, err
		}
		if origin := oaUrlOrigin(destination); !slices.Contains(app.ResourceOrigins, origin) {
			release()
			shown := origin
			if shown == "" {
				shown = destination
			}
			return nil, &domain.Invalid{Msg: fmt.Sprintf("Auth config %s holds platform-managed credentials that may not be sent to '%s'.", a.ID, shown)}
		}
	}
	creds, err := oaLoadCredentials(ctx, s.d.Secrets.Manager(sess, a.CreatedBy), a)
	release()
	if err != nil {
		return nil, err
	}
	switch a.AuthType {
	case "api_key":
		name := "X-API-Key"
		if n, ok := a.Config["header_name"].(string); ok && n != "" {
			name = n
		}
		v := oaPyStr(creds["header_value"])
		if v == "" {
			return nil, &domain.Invalid{Msg: fmt.Sprintf("Auth config %s has no API key stored. Re-enter its credentials.", a.ID)}
		}
		return map[string]string{name: v}, nil
	case "bearer":
		t := oaPyStr(creds["token"])
		if t == "" {
			return nil, &domain.Invalid{Msg: fmt.Sprintf("Auth config %s has no bearer token stored. Re-enter its credentials.", a.ID)}
		}
		return map[string]string{"Authorization": "Bearer " + t}, nil
	case "oauth2":
		token, err := s.oauthToken(ctx, ws, a, creds, forceRefresh)
		if err != nil {
			return nil, err
		}
		scheme := oaPyStr(a.Config["authorization_scheme"])
		if scheme == "" {
			scheme = "Bearer"
		}
		return map[string]string{"Authorization": scheme + " " + token}, nil
	}
	return map[string]string{}, nil
}

// oauthToken is _get_oauth2_token with refreshes serialized per auth config:
// the holder of the lock re-reads the stored credentials and uses a token
// another holder renewed meanwhile instead of spending the refresh token again.
func (s *Service) oauthToken(ctx context.Context, ws scope.Workspace, a domain.AuthConfig, creds map[string]any, force bool) (string, error) {
	seen := oaPyStr(creds["access_token"])
	if !s.needsRefresh(creds, force) {
		return seen, nil
	}
	var token string
	err := s.d.DB.Lock(ctx, db.TextKey("mcp_auth_refresh:"+a.ID), func(ctx context.Context, q db.Querier) error {
		sess := db.NewTxSession(ws, q)
		id, err := uuid.Parse(a.ID)
		if err != nil {
			return err
		}
		cur, ok, err := s.d.Auth.Get(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return &domain.Invalid{Msg: fmt.Sprintf("Auth config %s not found in this workspace", a.ID)}
		}
		m := s.d.Secrets.Manager(sess, cur.CreatedBy)
		fresh, err := oaLoadCredentials(ctx, m, cur)
		if err != nil {
			return err
		}
		if t := oaPyStr(fresh["access_token"]); t != "" && t != seen && !s.needsRefresh(fresh, false) {
			token = t
			return nil
		}
		token, err = s.refreshToken(ctx, sess, m, cur, fresh)
		return err
	})
	return token, err
}

func (s *Service) needsRefresh(creds map[string]any, force bool) bool {
	if force || oaPyStr(creds["access_token"]) == "" {
		return true
	}
	exp, ok := oaPyFloat(creds["expires_at"])
	return ok && s.unixNow() >= exp-30
}

func (s *Service) unixNow() float64 {
	return float64(s.d.Now().UnixNano()) / 1e9
}

// refreshToken is _refresh_oauth2_token: a refresh_token grant, else
// client_credentials when a secret is held, else the user must reconnect.
func (s *Service) refreshToken(ctx context.Context, sess db.Session, m secretGetter, a domain.AuthConfig, creds map[string]any) (string, error) {
	clientID, secret, err := s.clientCredentials(ctx, m, a, creds, false)
	if err != nil {
		return "", err
	}
	refresh := oaPyStr(creds["refresh_token"])
	form := url.Values{}
	switch {
	case refresh != "":
		form.Set("grant_type", "refresh_token")
		form.Set("refresh_token", refresh)
		form.Set("client_id", clientID)
	case secret != "":
		form.Set("grant_type", "client_credentials")
		form.Set("client_id", clientID)
		form.Set("scope", strings.Join(domain.StringList(a.Config["scopes"]), " "))
	default:
		return "", &domain.ReauthRequired{Msg: fmt.Sprintf("auth config %s has no refresh_token or client_secret; reconnect required", a.ID)}
	}
	data, status, err := s.tokenRequest(ctx, a, form, clientID, secret)
	if err != nil {
		return "", err
	}
	if status >= 400 && status < 500 {
		return "", &domain.ReauthRequired{Msg: fmt.Sprintf("token refresh rejected (%d) for auth config %s; reconnect required", status, a.ID)}
	}
	if status < 200 || status >= 300 {
		return "", fmt.Errorf("token endpoint of auth config %s answered %d", a.ID, status)
	}
	if data == nil {
		return "", fmt.Errorf("token endpoint of auth config %s answered no JSON object", a.ID)
	}
	_, hasErr := data["error"]
	access, hasToken := data["access_token"]
	if hasErr || !hasToken {
		reason := "no access_token"
		if hasErr {
			reason = oaPyStr(data["error"])
		}
		return "", &domain.ReauthRequired{Msg: fmt.Sprintf("token refresh rejected (%s) for auth config %s; reconnect required", reason, a.ID)}
	}
	token := oaPyStr(access)
	creds["access_token"] = token
	s.setExpiry(creds, data["expires_in"])
	if rt, ok := data["refresh_token"]; ok {
		creds["refresh_token"] = rt
	}
	if err := s.writeCredentials(ctx, sess, m, a, creds); err != nil {
		return "", err
	}
	s.d.Log.InfoContext(ctx, "Refreshed OAuth2 token", "auth_config_id", a.ID)
	return token, nil
}

// writeCredentials stores creds under the config's own secret name and
// records it on a config that had none, so the next read finds them.
func (s *Service) writeCredentials(ctx context.Context, sess db.Session, m secretGetter, a domain.AuthConfig, creds map[string]any) error {
	raw, err := oaMarshalCreds(creds)
	if err != nil {
		return err
	}
	key := domain.SecretKeyFor(a.ID)
	if err := m.Set(ctx, key, raw); err != nil {
		return err
	}
	if a.SecretKey != nil && *a.SecretKey == key {
		return nil
	}
	id, err := uuid.Parse(a.ID)
	if err != nil {
		return err
	}
	return s.d.Auth.SetSecretKey(ctx, sess, id, key, s.d.Now())
}

// setExpiry is _set_expiry: int(expires_in) seconds from now, none when it is not one.
func (s *Service) setExpiry(creds map[string]any, expiresIn any) {
	n, ok := oaPyInt(expiresIn)
	if !ok {
		delete(creds, "expires_at")
		return
	}
	creds["expires_at"] = s.unixNow() + float64(n)
}

// clientCredentials is get_oauth_client_credentials: the client id and
// secret a config authenticates with, a platform app's when it names one.
func (s *Service) clientCredentials(ctx context.Context, m secretGetter, a domain.AuthConfig, creds map[string]any, requireSecret bool) (string, string, error) {
	if a.AuthType != "oauth2" {
		return "", "", &domain.Invalid{Msg: fmt.Sprintf("Auth config %s is not OAuth2", a.ID)}
	}
	clientID := oaPyStr(a.Config["client_id"])
	secret := oaPyStr(creds["client_secret"])
	if name := oaPyStr(a.Config["client_id_secret_name"]); name != "" {
		v, err := oaGetSecret(ctx, m, name)
		if err != nil {
			return "", "", err
		}
		clientID = v
	}
	if name := oaPyStr(a.Config["client_secret_secret_name"]); name != "" {
		v, err := oaGetSecret(ctx, m, name)
		if err != nil {
			return "", "", err
		}
		secret = v
	}
	app, err := s.platformApp(a)
	if err != nil {
		return "", "", err
	}
	if app != nil {
		clientID, secret = app.ClientID, app.ClientSecret
	}
	if clientID == "" || (requireSecret && secret == "") {
		return "", "", &domain.Invalid{Msg: fmt.Sprintf("OAuth client credentials are incomplete for auth config %s.", a.ID)}
	}
	return clientID, secret, nil
}

// platformApp is platform_oauth_app_for: nil for a config that is not managed.
func (s *Service) platformApp(a domain.AuthConfig) (*OAuthApp, error) {
	if !domain.IsManaged(a.Config) {
		return nil, nil
	}
	issuer := oaPyStr(a.Config["platform_oauth_issuer"])
	if issuer == "" {
		return nil, &domain.Invalid{Msg: fmt.Sprintf("Auth config %s is platform-managed but names no platform OAuth app. Reconnect it.", a.ID)}
	}
	app := s.d.Config.App(oaNormalizeIssuer(issuer))
	if app == nil {
		return nil, &domain.Invalid{Msg: fmt.Sprintf("Auth config %s authorizes through the platform OAuth app for %s, which AGENTAREA_MCP_OAUTH_APPS does not configure.", a.ID, issuer)}
	}
	return app, nil
}

func oaGetSecret(ctx context.Context, m secretGetter, name string) (string, error) {
	v, err := m.Get(ctx, name)
	if errors.Is(err, errSecretNotFound) {
		return "", nil
	}
	return v, err
}
