package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
)

// OAuthError is a refusal of the connect flow as Python raises it: with a
// Code it is an AppError (problem code, and the issuer extension when
// WithIssuer), without one an HTTPException.
type OAuthError struct {
	Status     int
	Code       string
	Msg        string
	Issuer     *string
	WithIssuer bool
}

func (e *OAuthError) Error() string { return e.Msg }

func oaHttpErr(status int, msg string) *OAuthError { return &OAuthError{Status: status, Msg: msg} }

func oaAppRequired(detail, issuer string) *OAuthError {
	e := &OAuthError{Status: 422, Code: "oauth_app_required", Msg: detail, WithIssuer: true}
	if issuer != "" {
		e.Issuer = &issuer
	}
	return e
}

// notAuthorizable is NotAuthorizableError: preflight renders it as
// unsupported, authorize answers its status.
type notAuthorizable struct {
	detail string
	status int
}

func (e *notAuthorizable) Error() string { return e.detail }

const (
	kindMCPInstance       = "mcp_instance"
	kindOpenAPIConnection = "openapi_connection"
	oauthStateTTL         = 600 * time.Second
	callbackPath          = "/v1/oauth/callback"
)

// OAuthTarget names what a flow connects; exactly one id is set.
type OAuthTarget struct {
	InstanceID          *uuid.UUID
	ServerID            *uuid.UUID
	CatalogItemID       *uuid.UUID
	OpenAPIConnectionID *uuid.UUID
}

// Preflight is OAuthPreflightResponse without the redirect URI.
type Preflight struct {
	Status                string
	CredentialSource      *string
	ClientID              *string
	Connected             bool
	Detail                string
	Issuer                *string
	AuthorizationEndpoint *string
	Scopes                []string
	DefaultScopes         []string
	// InstallURL is the install page of the platform app the connection's
	// credential was minted through, where the user picks what it reaches.
	InstallURL *string
}

// CustomOAuthApp is CustomOAuthAppFields, already validated (one source per credential).
type CustomOAuthApp struct {
	ClientID             *string
	ClientSecret         *string
	ClientIDSecretID     *uuid.UUID
	ClientSecretSecretID *uuid.UUID
}

// AuthorizeRequest is OAuthAuthorizeRequest, validated.
type AuthorizeRequest struct {
	Target OAuthTarget
	// Mode is auto or custom.
	Mode   string
	Custom CustomOAuthApp
	// Scopes is the pick when ScopesSet; unset asks for the default.
	Scopes    []string
	ScopesSet bool
	ReturnTo  string
}

// oauthState is the flow between authorize, the callback and the finish
// (oauth_connect/state.py), with the workspace slug the landing page needs.
type oauthState struct {
	TargetKind    string   `json:"target_kind"`
	ConnectionID  string   `json:"connection_id"`
	AuthConfigID  string   `json:"auth_config_id"`
	WorkspaceID   string   `json:"workspace_id"`
	UserID        string   `json:"user_id"`
	CodeVerifier  string   `json:"code_verifier"`
	ReturnTo      string   `json:"return_to"`
	Scopes        []string `json:"scopes"`
	WorkspaceSlug string   `json:"workspace_slug,omitempty"`
}

type returnedFlow struct {
	Flow oauthState `json:"flow"`
	Code string     `json:"code"`
}

// target is one connection kind a flow signs in to.
type oauthTarget struct {
	connected bool
	current   *domain.AuthConfig
	profile   func(ctx context.Context) (oauthProfile, error)
	required  func(p oauthProfile) string
	ensure    func(ctx context.Context) error
	create    func(ctx context.Context) (string, uuid.UUID, error)
	authName  func(id uuid.UUID) string
}

// OAuthCallbackURI is the one redirect URI every provider sends the browser back to.
func (s *Service) OAuthCallbackURI() string {
	return strings.TrimRight(s.d.APIURL, "/") + callbackPath
}

func oauthAppRequiredDetail(issuer string) string {
	return issuer + " does not support Dynamic Client Registration (RFC 7591), so AgentArea " +
		"cannot register itself. Register an OAuth app with this provider and connect with " +
		"its client ID and secret."
}

func oaFirstNonEmpty(a, b string) string {
	if a != "" {
		return a
	}
	return b
}

func oaConfigScopes(a *domain.AuthConfig) []string {
	if a == nil {
		return nil
	}
	l, ok := a.Config["scopes"].([]any)
	if !ok {
		return nil
	}
	return oaStringList(l)
}

// oaMissingScopes is what the last check was refused for lacking (insufficient_scope).
func oaMissingScopes(verification map[string]any) []string {
	e, _ := verification["error"].(map[string]any)
	d, _ := e["detail"].(map[string]any)
	if d == nil || d["error"] != "insufficient_scope" {
		return nil
	}
	l, ok := d["required_scopes"].([]any)
	if !ok {
		return nil
	}
	var out []string
	for _, v := range l {
		if s, ok := v.(string); ok && s != "" {
			out = append(out, s)
		}
	}
	return out
}

// oaNormalizeURLKeys is _normalize_url_keys: a url spec's legacy url keys become endpoint_url.
func oaNormalizeURLKeys(spec map[string]any) map[string]any {
	if spec["type"] != "url" || domain.Truthy(spec["endpoint_url"]) {
		return spec
	}
	for _, legacy := range []string{"url", "external_url"} {
		if v, ok := spec[legacy].(string); ok && strings.TrimSpace(v) != "" {
			spec["endpoint_url"] = v
			delete(spec, legacy)
			return spec
		}
	}
	return spec
}

// oaServerTransportSpec is server_transport_spec, as far as the URL transport needs it.
func oaServerTransportSpec(sp *catalogapi.MCPSpec) map[string]any {
	out := map[string]any{}
	if sp == nil {
		return out
	}
	for k, v := range sp.JSONSpec {
		out[k] = v
	}
	setDefault := func(k string, v any) {
		if _, ok := out[k]; !ok {
			out[k] = v
		}
	}
	switch {
	case sp.RemoteURL != nil && *sp.RemoteURL != "":
		setDefault("type", domain.TransportURL)
		setDefault("endpoint_url", *sp.RemoteURL)
	case len(sp.Cmd) > 0:
		setDefault("type", domain.TransportCommand)
	case sp.DockerImageURL != nil && *sp.DockerImageURL != "":
		setDefault("type", domain.TransportDocker)
	}
	return oaNormalizeURLKeys(out)
}

func oaSpecRemoteURL(sp *catalogapi.MCPSpec) string {
	spec := oaServerTransportSpec(sp)
	if spec["type"] != domain.TransportURL {
		return ""
	}
	return oaPyStr(spec["endpoint_url"])
}

// oaInstanceRemoteURL is instance_remote_url: a URL instance's endpoint, its
// own config over its spec's.
func oaInstanceRemoteURL(inst domain.Instance, sp *catalogapi.MCPSpec) string {
	if sp == nil || inst.Transport != domain.TransportURL {
		return ""
	}
	merged := oaServerTransportSpec(sp)
	for k, v := range inst.JSONSpec {
		merged[k] = v
	}
	merged["type"] = domain.TransportURL
	return oaPyStr(oaNormalizeURLKeys(merged)["endpoint_url"])
}

func oaSpecJSON(sp *catalogapi.MCPSpec) map[string]any {
	if sp == nil {
		return nil
	}
	return sp.JSONSpec
}

func oaInvalidSpec(err error) error {
	return &notAuthorizable{detail: "The MCP server spec's OAuth settings are invalid: " + err.Error(), status: 502}
}

// discovered is _discovered: a remote MCP server's profile from discovery.
func (s *Service) discovered(ctx context.Context, mcpURL string, jsonSpec map[string]any) (oauthProfile, error) {
	if mcpURL == "" {
		return oauthProfile{}, &notAuthorizable{detail: "No remote URL configured. OAuth connect requires a URL-type MCP connection.", status: 400}
	}
	params, err := oaSpecAuthorizeParams(jsonSpec)
	if err != nil {
		return oauthProfile{}, oaInvalidSpec(err)
	}
	defaults, err := oaSpecDefaultScopes(jsonSpec)
	if err != nil {
		return oauthProfile{}, oaInvalidSpec(err)
	}
	meta, err := s.discoverAuthServer(ctx, mcpURL)
	if err != nil {
		return oauthProfile{}, &notAuthorizable{detail: err.Error(), status: 502}
	}
	p, err := oaDiscoveredProfile(meta, mcpURL, params, defaults)
	if err != nil {
		return oauthProfile{}, oaInvalidSpec(err)
	}
	return p, nil
}

func (s *Service) specs() (Specs, error) {
	if s.d.Specs == nil {
		return nil, &domain.Unavailable{Msg: "MCP server specs are not available"}
	}
	return s.d.Specs, nil
}

func (s *Service) instanceTarget(ctx context.Context, c authn.Caller, id uuid.UUID) (oauthTarget, error) {
	specs, err := s.specs()
	if err != nil {
		return oauthTarget{}, err
	}
	var inst domain.Instance
	var cur *domain.AuthConfig
	err = s.read(ctx, c, func(sess db.Session) error {
		i, ok, err := s.d.Instances.Get(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return &domain.NotFound{Msg: "MCP instance not found"}
		}
		inst = i
		if i.AuthConfigID == nil {
			return nil
		}
		aid, err := uuid.Parse(*i.AuthConfigID)
		if err != nil {
			return err
		}
		a, ok, err := s.d.Auth.Get(ctx, sess, aid)
		if ok {
			cur = &a
		}
		return err
	})
	if err != nil {
		return oauthTarget{}, err
	}
	var spec *catalogapi.MCPSpec
	if inst.ServerSpecID != "" {
		sp, ok, err := specs.Get(ctx, c.Workspace, inst.ServerSpecID, catalogapi.MCPSpecGet{PlatformBacked: inst.PlatformManaged()})
		if err != nil {
			return oauthTarget{}, err
		}
		if ok {
			spec = &sp
		}
	}
	current, missing := oaConfigScopes(cur), oaMissingScopes(inst.VerificationRaw)
	remote := oaInstanceRemoteURL(inst, spec)
	return oauthTarget{
		connected: inst.AuthConfigID != nil,
		current:   cur,
		profile: func(ctx context.Context) (oauthProfile, error) {
			p, err := s.discovered(ctx, remote, oaSpecJSON(spec))
			if err != nil {
				return p, err
			}
			offered := oaDedupe(append(slices.Clone(p.Scopes), missing...))
			var still []string
			for _, sc := range current {
				if slices.Contains(offered, sc) {
					still = append(still, sc)
				}
			}
			p.Scopes = offered
			if len(still) > 0 {
				p.DefaultScopes = oaDedupe(append(still, missing...))
			}
			return p, nil
		},
		required: func(p oauthProfile) string {
			return oauthAppRequiredDetail(oaFirstNonEmpty(p.Issuer, p.AuthorizationEndpoint))
		},
		ensure: func(ctx context.Context) error { return s.Require(ctx, c, "edit", "mcp_instance", inst.ID) },
		create: func(context.Context) (string, uuid.UUID, error) { return kindMCPInstance, id, nil },
		authName: func(id uuid.UUID) string {
			return "mcp-oauth-" + id.String()[:8]
		},
	}, nil
}

func (s *Service) specTarget(ctx context.Context, c authn.Caller, id uuid.UUID) (oauthTarget, error) {
	specs, err := s.specs()
	if err != nil {
		return oauthTarget{}, err
	}
	sp, ok, err := specs.Get(ctx, c.Workspace, id.String(), catalogapi.MCPSpecGet{})
	if err != nil {
		return oauthTarget{}, err
	}
	if !ok {
		return oauthTarget{}, &domain.NotFound{Msg: "MCP server spec not found"}
	}
	return oauthTarget{
		profile: func(ctx context.Context) (oauthProfile, error) {
			return s.discovered(ctx, oaSpecRemoteURL(&sp), sp.JSONSpec)
		},
		required: func(p oauthProfile) string {
			return oauthAppRequiredDetail(oaFirstNonEmpty(p.Issuer, p.AuthorizationEndpoint))
		},
	}, nil
}

// oaHttpsOrigin is _origin: the exact https origin of a catalog URL.
func oaHttpsOrigin(raw string) (string, error) {
	u, err := url.Parse(raw)
	if err != nil || u.Scheme != "https" || u.Host == "" {
		return "", oaHttpErr(400, "Catalog OAuth URLs must use HTTPS")
	}
	return u.Scheme + "://" + u.Host, nil
}

// catalogOAuth is catalog_oauth_profile, checked before anything trusts it.
type catalogOAuth struct {
	provider, authorizationURL, tokenURL, scheme, method string
	scopes                                               []string
	params                                               map[string]string
	allowedRaw                                           any
}

func (s *Service) catalogOAuthProfile(ctx context.Context, spec map[string]any) (catalogOAuth, error) {
	oauth, ok := spec["oauth"].(map[string]any)
	if !ok {
		return catalogOAuth{}, oaHttpErr(400, "Connection does not support OAuth")
	}
	var missing []string
	for _, f := range []string{"provider_key", "authorization_url", "token_url"} {
		if !domain.Truthy(oauth[f]) {
			missing = append(missing, f)
		}
	}
	if len(missing) > 0 {
		return catalogOAuth{}, oaHttpErr(500, "Catalog OAuth template is missing: "+strings.Join(missing, ", "))
	}
	for _, f := range []string{"authorization_url", "token_url"} {
		raw := oaPyStr(oauth[f])
		if _, err := oaHttpsOrigin(raw); err != nil {
			return catalogOAuth{}, err
		}
		if g := s.d.Out.Guard(); g != nil {
			if _, err := g.CheckURL(ctx, raw); err != nil {
				return catalogOAuth{}, oaHttpErr(500, "Catalog OAuth URL is not allowed")
			}
		}
	}
	co := catalogOAuth{
		provider: oaPyStr(oauth["provider_key"]), authorizationURL: oaPyStr(oauth["authorization_url"]),
		tokenURL: oaPyStr(oauth["token_url"]), scheme: oaFirstNonEmpty(oaPyStr(oauth["authorization_scheme"]), "Bearer"),
		method: oaFirstNonEmpty(oaPyStr(oauth["client_auth_method"]), "client_secret_post"),
	}
	if co.scheme != "Bearer" && co.scheme != "OAuth" {
		return catalogOAuth{}, oaHttpErr(500, "Unsupported authorization scheme")
	}
	if co.method != "client_secret_post" && co.method != "client_secret_basic" {
		return catalogOAuth{}, oaHttpErr(500, "Unsupported OAuth client auth method")
	}
	co.scopes = []string{}
	if domain.Truthy(oauth["scopes"]) {
		l, ok := oauth["scopes"].([]any)
		if !ok {
			return catalogOAuth{}, oaHttpErr(500, "Invalid OAuth scopes")
		}
		for _, v := range l {
			sc, ok := v.(string)
			if !ok {
				return catalogOAuth{}, oaHttpErr(500, "Invalid OAuth scopes")
			}
			co.scopes = append(co.scopes, sc)
		}
	}
	co.params = map[string]string{}
	if domain.Truthy(oauth["authorize_params"]) {
		m, ok := oauth["authorize_params"].(map[string]any)
		if !ok {
			return catalogOAuth{}, oaHttpErr(500, "Invalid OAuth authorize params")
		}
		for k, v := range m {
			sv, ok := v.(string)
			if !ok {
				return catalogOAuth{}, oaHttpErr(500, "Invalid OAuth authorize params")
			}
			co.params[k] = sv
		}
		if oaCheckedAuthorizeParams(co.params) != nil {
			return catalogOAuth{}, oaHttpErr(500, "Invalid OAuth authorize params")
		}
	}
	if domain.Truthy(oauth["allowed_api_origins"]) {
		co.allowedRaw = oauth["allowed_api_origins"]
	}
	return co, nil
}

func (s *Service) catalogTarget(ctx context.Context, c authn.Caller, id uuid.UUID) (oauthTarget, error) {
	if s.d.CatalogItems == nil {
		return oauthTarget{}, &domain.Unavailable{Msg: "Catalog API connections are not available"}
	}
	item, err := s.d.CatalogItems.CatalogAPIItem(ctx, c.Workspace, id)
	if err != nil {
		return oauthTarget{}, err
	}
	co, err := s.catalogOAuthProfile(ctx, item.Spec)
	if err != nil {
		return oauthTarget{}, err
	}
	base, err := oaHttpsOrigin(oaPyStr(item.Spec["base_url"]))
	if err != nil {
		return oauthTarget{}, err
	}
	allowed := []string{base}
	if co.allowedRaw != nil {
		l, ok := co.allowedRaw.([]any)
		if !ok || !slices.Contains(l, any(base)) {
			return oauthTarget{}, oaHttpErr(500, "Catalog OAuth API origin is not allowlisted")
		}
		allowed = allowed[:0]
		for _, o := range l {
			exact, err := oaHttpsOrigin(oaPyStr(o))
			if err != nil {
				return oauthTarget{}, err
			}
			if str, isStr := o.(string); !isStr || exact != str {
				return oauthTarget{}, oaHttpErr(500, "Catalog OAuth origin must be an exact origin")
			}
			allowed = append(allowed, exact)
		}
	}
	name := item.Name
	return oauthTarget{
		profile: func(context.Context) (oauthProfile, error) {
			return oauthProfile{
				Provider: co.provider, AuthorizationEndpoint: co.authorizationURL, TokenEndpoint: co.tokenURL,
				ResourceOrigins: allowed, Scopes: co.scopes, AuthorizeParams: co.params,
				AuthorizationScheme: co.scheme, ClientAuthMethod: co.method,
			}, nil
		},
		required: func(oauthProfile) string {
			return "This AgentArea installation has no OAuth app for " + name + ". Register your own OAuth app with " +
				name + " using the redirect URI below, then enter its client ID and client secret."
		},
		ensure: func(context.Context) error { return nil },
		create: func(ctx context.Context) (string, uuid.UUID, error) {
			in := ConnectionCreate{Name: item.Name, Description: item.Description, AllowedAuthOrigins: allowed, Status: "pending"}
			if domain.Truthy(item.Spec["base_url"]) {
				in.BaseURL = oaPyStr(item.Spec["base_url"])
			}
			if u, ok := item.Spec["spec_url"].(string); ok {
				in.SpecURL = &u
			}
			if content, ok := item.Spec["spec_content"].(map[string]any); ok {
				in.SpecContent = content
			}
			v, err := s.CreateConnection(ctx, c, in, &item.ID)
			if err != nil {
				return "", uuid.Nil, err
			}
			connID, err := uuid.Parse(v.Connection.ID)
			return kindOpenAPIConnection, connID, err
		},
		authName: func(id uuid.UUID) string { return co.provider + "-" + id.String()[:8] },
	}, nil
}

func (s *Service) connectionTarget(ctx context.Context, c authn.Caller, id uuid.UUID) (oauthTarget, error) {
	var conn domain.Connection
	var cur *domain.AuthConfig
	err := s.read(ctx, c, func(sess db.Session) error {
		cn, ok, err := s.d.Connections.Get(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return domain.ErrConnectionNotFound()
		}
		conn = cn
		if cn.AuthConfigID == nil {
			return nil
		}
		aid, err := uuid.Parse(*cn.AuthConfigID)
		if err != nil {
			return err
		}
		a, ok, err := s.d.Auth.Get(ctx, sess, aid)
		if ok {
			cur = &a
		}
		return err
	})
	if err != nil {
		return oauthTarget{}, err
	}
	var catalog *oauthTarget
	if conn.RegistryItemID != nil {
		item, err := uuid.Parse(*conn.RegistryItemID)
		if err != nil {
			return oauthTarget{}, err
		}
		t, err := s.catalogTarget(ctx, c, item)
		if err != nil {
			return oauthTarget{}, err
		}
		catalog = &t
	}
	current := oaConfigScopes(cur)
	return oauthTarget{
		connected: conn.AuthConfigID != nil,
		current:   cur,
		profile: func(ctx context.Context) (oauthProfile, error) {
			if catalog == nil {
				return oauthProfile{}, &notAuthorizable{detail: "This API connection was not made from a catalog API, so it has no sign-in to repeat.", status: 400}
			}
			p, err := catalog.profile(ctx)
			if err != nil {
				return p, err
			}
			var still []string
			for _, sc := range current {
				if slices.Contains(p.Scopes, sc) {
					still = append(still, sc)
				}
			}
			if len(still) > 0 {
				p.DefaultScopes = still
			}
			return p, nil
		},
		required: func(p oauthProfile) string { return catalog.required(p) },
		ensure: func(ctx context.Context) error {
			return s.Require(ctx, c, "edit", "openapi_connection", conn.ID)
		},
		create: func(context.Context) (string, uuid.UUID, error) { return kindOpenAPIConnection, id, nil },
		authName: func(id uuid.UUID) string {
			if catalog == nil {
				return "oauth-" + id.String()[:8]
			}
			return catalog.authName(id)
		},
	}, nil
}

func (s *Service) loadTarget(ctx context.Context, c authn.Caller, t OAuthTarget) (oauthTarget, error) {
	switch {
	case t.InstanceID != nil:
		return s.instanceTarget(ctx, c, *t.InstanceID)
	case t.ServerID != nil:
		return s.specTarget(ctx, c, *t.ServerID)
	case t.CatalogItemID != nil:
		return s.catalogTarget(ctx, c, *t.CatalogItemID)
	case t.OpenAPIConnectionID != nil:
		return s.connectionTarget(ctx, c, *t.OpenAPIConnectionID)
	}
	return oauthTarget{}, oaHttpErr(422, "No target to inspect.")
}

// oaOwnApp is _own_app: the custom app a reconnect may sign in with again,
// only against the endpoints it was registered with.
func oaOwnApp(cur *domain.AuthConfig, p oauthProfile) *domain.AuthConfig {
	if cur == nil || cur.Config["credential_mode"] != "custom" {
		return nil
	}
	if cur.Config["authorization_url"] != p.AuthorizationEndpoint || cur.Config["token_url"] != p.TokenEndpoint {
		return nil
	}
	return cur
}

func oaOptional(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

// OAuthPreflight is preflight: every outcome is an answer.
func (s *Service) OAuthPreflight(ctx context.Context, c authn.Caller, ref OAuthTarget) (Preflight, error) {
	t, err := s.loadTarget(ctx, c, ref)
	if err != nil {
		return Preflight{}, err
	}
	p, err := t.profile(ctx)
	var na *notAuthorizable
	if errors.As(err, &na) {
		return Preflight{Status: "unsupported", Connected: t.connected, Detail: na.detail, Scopes: []string{}, DefaultScopes: []string{}}, nil
	}
	if err != nil {
		return Preflight{}, err
	}
	own := oaOwnApp(t.current, p)
	source := s.autoSource(p)
	if own != nil {
		source = "custom"
	}
	out := Preflight{
		Status: "ready", Connected: t.connected, CredentialSource: oaOptional(source),
		Issuer: oaOptional(p.Issuer), AuthorizationEndpoint: &p.AuthorizationEndpoint,
		Scopes: oaNonNil(p.Scopes),
	}
	if own != nil {
		if id, ok := own.Config["client_id"].(string); ok {
			out.ClientID = &id
		}
	}
	if source == "" {
		out.Status = "oauth_app_required"
		out.Detail = t.required(p)
	}
	def, _ := p.requestedScopes(nil, false)
	out.DefaultScopes = oaNonNil(def)
	out.InstallURL = oaOptional(s.installURL(t.current))
	return out, nil
}

// installURL is the install page of the platform app a credential was minted
// through; empty for any other credential.
func (s *Service) installURL(a *domain.AuthConfig) string {
	if a == nil {
		return ""
	}
	app, err := s.platformApp(*a)
	if err != nil || app == nil {
		return ""
	}
	return app.InstallURL
}

func oaNonNil(l []string) []string {
	if l == nil {
		return []string{}
	}
	return l
}

// resolvedApp is ResolvedOAuthApp: credentials split the way an auth config stores them.
type resolvedApp struct {
	clientID    string
	config      map[string]any
	credentials map[string]any
	refs        [][2]string
}

// OAuthAuthorize starts a sign-in and returns the provider's authorization
// URL and the connection the callback attaches the credential to.
func (s *Service) OAuthAuthorize(ctx context.Context, c authn.Caller, req AuthorizeRequest) (string, uuid.UUID, error) {
	t, err := s.loadTarget(ctx, c, req.Target)
	if err != nil {
		return "", uuid.Nil, err
	}
	if err := t.ensure(ctx); err != nil {
		return "", uuid.Nil, err
	}
	p, err := t.profile(ctx)
	var na *notAuthorizable
	if errors.As(err, &na) {
		s.countOAuth("unknown", "failed:not_authorizable")
		return "", uuid.Nil, oaHttpErr(na.status, na.detail)
	}
	if err != nil {
		return "", uuid.Nil, err
	}
	requested, err := p.requestedScopes(req.Scopes, req.ScopesSet)
	if err != nil {
		return "", uuid.Nil, &OAuthError{Status: 422, Code: "invalid_scopes", Msg: err.Error()}
	}
	var own *domain.AuthConfig
	if req.Mode != "custom" {
		own = oaOwnApp(t.current, p)
	}
	var (
		authID   string
		clientID string
		kind     string
		connID   uuid.UUID
	)
	if own != nil {
		if clientID, err = s.ownClient(ctx, c, *own, p); err != nil {
			return "", uuid.Nil, err
		}
		authID = own.ID
		if kind, connID, err = t.create(ctx); err != nil {
			return "", uuid.Nil, err
		}
	} else {
		var r resolvedApp
		if req.Mode == "custom" {
			if r, err = s.resolveCustomApp(ctx, c, req.Custom); err != nil {
				return "", uuid.Nil, err
			}
			r.config["credential_mode"] = "custom"
		} else if p, r, err = s.autoClient(ctx, t, p); err != nil {
			return "", uuid.Nil, err
		}
		if kind, connID, err = t.create(ctx); err != nil {
			return "", uuid.Nil, err
		}
		cfg := map[string]any{
			"provider": p.Provider, "authorization_url": p.AuthorizationEndpoint, "token_url": p.TokenEndpoint,
			"scopes": requested, "authorization_scheme": oaFirstNonEmpty(p.AuthorizationScheme, "Bearer"),
			"client_auth_method": oaFirstNonEmpty(p.ClientAuthMethod, "client_secret_post"),
		}
		if p.Issuer != "" {
			cfg["issuer"] = p.Issuer
		}
		for k, v := range r.config {
			cfg[k] = v
		}
		a, err := s.mintAuthConfig(ctx, c, t.authName(connID), cfg, r.credentials, kind, connID)
		if err != nil {
			return "", uuid.Nil, err
		}
		cat := s.d.Catalog(c.Workspace, actor(c))
		for _, ref := range r.refs {
			if err := cat.AddReference(ctx, ref[0], "mcp_auth_config", a.ID, ref[1]); err != nil {
				return "", uuid.Nil, err
			}
		}
		authID, clientID = a.ID, r.clientID
	}
	verifier, challenge := oaPkcePair()
	token := oaTokenURLSafe(32)
	st := oauthState{
		TargetKind: kind, ConnectionID: connID.String(), AuthConfigID: authID,
		WorkspaceID: c.Workspace.ID(), UserID: c.UserID, CodeVerifier: verifier,
		ReturnTo: req.ReturnTo, WorkspaceSlug: c.Workspace.Slug(),
	}
	if own != nil {
		st.Scopes = slices.Clone(requested)
	}
	raw, err := json.Marshal(st)
	if err != nil {
		return "", uuid.Nil, err
	}
	if err := s.d.KV.SetEx(ctx, "oauth_state:"+token, string(raw), oauthStateTTL); err != nil {
		return "", uuid.Nil, err
	}
	loc := oaAuthorizeURL(p, clientID, s.OAuthCallbackURI(), challenge, token, requested)
	s.countOAuth(s.oauthProvider(p.Issuer), "started")
	return loc, connID, nil
}

// ownClient is _own_client: the connection's own app, for whoever may put its credential to use.
func (s *Service) ownClient(ctx context.Context, c authn.Caller, own domain.AuthConfig, p oauthProfile) (string, error) {
	id, err := uuid.Parse(own.ID)
	if err != nil {
		return "", err
	}
	var clientID string
	err = s.read(ctx, c, func(sess db.Session) error {
		a, err := s.GetAuthConfigForUse(ctx, sess, c, id)
		var fb *domain.Forbidden
		if errors.As(err, &fb) {
			return oaHttpErr(403, fb.Msg+" Connect with your own OAuth app instead.")
		}
		if err != nil {
			return err
		}
		m := s.d.Secrets.Manager(sess, c.UserID)
		creds, err := oaLoadCredentials(ctx, m, a)
		if err == nil {
			clientID, _, err = s.clientCredentials(ctx, m, a, creds, true)
		}
		var inv *domain.Invalid
		if errors.As(err, &inv) {
			s.d.Log.WarnContext(ctx, "Own OAuth app is incomplete", "auth_config_id", a.ID, "error", err)
			s.countOAuth(s.oauthProvider(p.Issuer), "failed:oauth_app_required")
			return oaAppRequired(inv.Msg+" Enter the OAuth app's client ID and secret again.", p.Issuer)
		}
		return err
	})
	return clientID, err
}

// autoClient picks the operator's platform app, else registers dynamically.
func (s *Service) autoClient(ctx context.Context, t oauthTarget, p oauthProfile) (oauthProfile, resolvedApp, error) {
	switch s.autoSource(p) {
	case "platform":
		app := s.platformAppFor(p)
		p.Issuer, p.AuthorizationEndpoint, p.TokenEndpoint = app.Issuer, app.AuthorizationEndpoint, app.TokenEndpoint
		return p, resolvedApp{clientID: app.ClientID, config: map[string]any{
			"credential_mode": "managed", "platform_oauth_issuer": app.Issuer,
		}, credentials: map[string]any{}}, nil
	case "dynamic":
		id, secret, err := s.registerClient(ctx, p.RegistrationEndpoint, s.OAuthCallbackURI())
		if err != nil {
			s.d.Log.InfoContext(ctx, "DCR failed", "issuer", p.Issuer, "error", err)
			s.countOAuth(s.oauthProvider(p.Issuer), "failed:dcr_failed")
			return p, resolvedApp{}, oaAppRequired(fmt.Sprintf("Dynamic client registration with %s failed (%v). Connect with an OAuth app you registered with this provider.", p.Issuer, err), p.Issuer)
		}
		r := resolvedApp{clientID: id, config: map[string]any{"client_id": id, "credential_mode": "dynamic"}, credentials: map[string]any{}}
		if secret != "" {
			r.credentials["client_secret"] = secret
		}
		return p, r, nil
	}
	s.countOAuth(s.oauthProvider(p.Issuer), "failed:oauth_app_required")
	return p, resolvedApp{}, oaAppRequired(t.required(p), p.Issuer)
}

// resolveCustomApp is resolve_custom_oauth_app: a referenced secret is
// stored by name, a typed-in one under the auth config.
func (s *Service) resolveCustomApp(ctx context.Context, c authn.Caller, f CustomOAuthApp) (resolvedApp, error) {
	r := resolvedApp{config: map[string]any{}, credentials: map[string]any{}}
	cat := s.d.Catalog(c.Workspace, actor(c))
	if f.ClientIDSecretID != nil {
		sec, v, err := s.workspaceSecretValue(ctx, c, cat, *f.ClientIDSecretID, "client ID")
		if err != nil {
			return r, err
		}
		r.clientID = v
		r.config["client_id_secret_name"] = sec.Name
		r.refs = append(r.refs, [2]string{sec.ID, "client_id"})
	} else if f.ClientID != nil {
		r.clientID = *f.ClientID
		r.config["client_id"] = *f.ClientID
	}
	if f.ClientSecretSecretID != nil {
		sec, _, err := s.workspaceSecretValue(ctx, c, cat, *f.ClientSecretSecretID, "client secret")
		if err != nil {
			return r, err
		}
		r.config["client_secret_secret_name"] = sec.Name
		r.refs = append(r.refs, [2]string{sec.ID, "client_secret"})
	} else if f.ClientSecret != nil {
		r.credentials["client_secret"] = *f.ClientSecret
	}
	return r, nil
}

func (s *Service) workspaceSecretValue(ctx context.Context, c authn.Caller, cat ksecrets.Catalog, id uuid.UUID, label string) (ksecrets.Secret, string, error) {
	sec, err := cat.GetForUse(ctx, id.String())
	switch {
	case errors.Is(err, ksecrets.ErrNotFound):
		return sec, "", oaHttpErr(422, "Selected OAuth "+label+" secret is not available in this workspace.")
	case errors.Is(err, ksecrets.ErrManaged):
		return sec, "", oaHttpErr(422, "Selected OAuth "+label+" must be a user-owned workspace secret.")
	case errors.Is(err, ksecrets.ErrAccessDenied):
		return sec, "", oaHttpErr(403, err.Error())
	case err != nil:
		return sec, "", err
	}
	var value string
	err = s.read(ctx, c, func(sess db.Session) error {
		v, err := oaGetSecret(ctx, s.d.Secrets.Manager(sess, c.UserID), sec.Name)
		value = v
		return err
	})
	if err != nil {
		return sec, "", err
	}
	if value == "" {
		return sec, "", oaHttpErr(422, "Selected OAuth "+label+" secret has no value.")
	}
	return sec, value, nil
}

// mintAuthConfig is MCPAuthService.create for a connect flow: the config
// belongs to the connection it is minted for and is deleted with it.
func (s *Service) mintAuthConfig(ctx context.Context, c authn.Caller, name string, cfg, creds map[string]any, kind string, owner uuid.UUID) (domain.AuthConfig, error) {
	if err := domain.ValidateConfig("oauth2", cfg); err != nil {
		return domain.AuthConfig{}, err
	}
	if s.d.OAuthStore == nil {
		return domain.AuthConfig{}, &domain.Unavailable{Msg: "OAuth connect is not available"}
	}
	var out domain.AuthConfig
	err := s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		id := s.d.NewID()
		a, err := s.d.OAuthStore.InsertOwnedAuth(ctx, sess, id, c.UserID, domain.AuthConfigNew{Name: name, AuthType: "oauth2", Config: cfg}, kind, owner, s.d.Now())
		if err != nil {
			return err
		}
		if len(creds) > 0 {
			key, err := s.storeCredentials(ctx, sess, c, a.ID, creds)
			if err != nil {
				return err
			}
			if err := s.d.Auth.SetSecretKey(ctx, sess, id, key, s.d.Now()); err != nil {
				return err
			}
			a.SecretKey = &key
		}
		out = a
		return nil
	})
	return out, err
}

func oaWithQuery(base string, pairs ...[2]string) string {
	parts := make([]string, len(pairs))
	for i, kv := range pairs {
		parts[i] = url.QueryEscape(kv[0]) + "=" + url.QueryEscape(kv[1])
	}
	return base + "?" + strings.Join(parts, "&")
}

// frontendBase is the frontend origin to return to: return_to's when it is AGENTAREA_APP_URL's own.
func (s *Service) frontendBase(returnTo string) string {
	def := strings.TrimRight(s.d.AppURL, "/")
	if returnTo == "" {
		return def
	}
	u, err := url.Parse(returnTo)
	exp, err2 := url.Parse(def)
	if err == nil && err2 == nil && (u.Scheme == "http" || u.Scheme == "https") && u.Host != "" &&
		u.Scheme == exp.Scheme && u.Host == exp.Host {
		return u.Scheme + "://" + u.Host
	}
	s.d.Log.Warn("Rejected non-matching return_to origin", "return_to", returnTo)
	return def
}

func (s *Service) connectPageURL(slug, id string) string {
	return strings.TrimRight(s.d.AppURL, "/") + "/w/" + slug + "/connect/" + id
}

func (s *Service) landingURL(f oauthState, slug string) string {
	if f.TargetKind == kindMCPInstance {
		if f.ReturnTo != "" {
			if u, err := url.Parse(f.ReturnTo); err == nil {
				page := (&url.URL{Scheme: u.Scheme, Host: u.Host, Path: u.Path}).String()
				if connect := s.connectPageURL(slug, f.ConnectionID); page == connect {
					return connect
				}
			}
		}
		return s.frontendBase(f.ReturnTo) + "/w/" + slug + "/connections/" + f.ConnectionID + "/settings"
	}
	return s.frontendBase(f.ReturnTo) + "/w/" + slug + "/connections/openapi/" + f.ConnectionID + "/settings"
}

// OAuthReceive is receive: the provider's redirect back. The code is parked
// for the person who started the flow; it returns where the browser goes.
func (s *Service) OAuthReceive(ctx context.Context, state, code, oauthErr, description string) (string, error) {
	var flow *oauthState
	if state != "" {
		raw, ok, err := s.d.KV.GetDel(ctx, "oauth_state:"+state)
		if err != nil {
			return "", err
		}
		if ok {
			var f oauthState
			if err := json.Unmarshal([]byte(raw), &f); err != nil {
				return "", err
			}
			flow = &f
		}
	}
	if flow == nil {
		s.countOAuth("unknown", "failed:"+oauthFailure(oauthErr, "invalid_state"))
		if oauthErr != "" {
			return oaWithQuery(s.frontendBase("")+"/", [2]string{"oauth", "error"}, [2]string{"reason", oaFirstNonEmpty(description, oauthErr)}), nil
		}
		return "", oaHttpErr(400, "Invalid or expired OAuth state")
	}
	if oauthErr != "" || code == "" {
		if flow.WorkspaceSlug == "" {
			return s.workspaceGone(*flow), nil
		}
		s.countOAuth("unknown", "failed:"+oauthFailure(oauthErr, "missing_code"))
		reason := oaFirstNonEmpty(description, oaFirstNonEmpty(oauthErr, "missing_code"))
		return oaWithQuery(s.landingURL(*flow, flow.WorkspaceSlug), [2]string{"oauth", "error"}, [2]string{"reason", reason}), nil
	}
	token := oaTokenURLSafe(32)
	raw, err := json.Marshal(returnedFlow{Flow: *flow, Code: code})
	if err != nil {
		return "", err
	}
	if err := s.d.KV.SetEx(ctx, "oauth_returned:"+token, string(raw), oauthStateTTL); err != nil {
		return "", err
	}
	return s.frontendBase(flow.ReturnTo) + "/oauth/finish?" + url.Values{"token": {token}}.Encode(), nil
}

func (s *Service) workspaceGone(f oauthState) string {
	s.countOAuth("unknown", "failed:workspace_gone")
	return oaWithQuery(s.frontendBase(f.ReturnTo)+"/", [2]string{"oauth", "error"}, [2]string{"reason", "workspace_gone"})
}

// OAuthFinish is finish: the flow's starter redeems the returned code.
// enter admits p into the flow's workspace; its failure is a workspace gone.
func (s *Service) OAuthFinish(ctx context.Context, p authn.Principal, token string, enter func(ctx context.Context, workspaceID string) (authn.Caller, error)) (string, error) {
	raw, ok, err := s.d.KV.GetDel(ctx, "oauth_returned:"+token)
	if err != nil {
		return "", err
	}
	if !ok {
		s.countOAuth("unknown", "failed:invalid_state")
		return "", oaHttpErr(400, "Invalid or expired OAuth sign-in")
	}
	var r returnedFlow
	if err := json.Unmarshal([]byte(raw), &r); err != nil {
		return "", err
	}
	flow := r.Flow
	if flow.UserID != p.UserID || !slices.Contains(p.AccessibleWorkspaces, flow.WorkspaceID) {
		s.d.Log.WarnContext(ctx, "OAuth finish refused", "target_kind", flow.TargetKind, "connection_id", flow.ConnectionID,
			"workspace_id", flow.WorkspaceID, "started_by", flow.UserID, "finished_by", p.UserID)
		s.countOAuth("unknown", "failed:other_user")
		return "", oaHttpErr(403, "This sign-in was started by someone else")
	}
	c, err := enter(ctx, flow.WorkspaceID)
	if err != nil {
		s.d.Log.WarnContext(ctx, "OAuth flow's workspace is gone", "workspace_id", flow.WorkspaceID, "error", err)
		return s.workspaceGone(flow), nil
	}
	landing := s.landingURL(flow, oaFirstNonEmpty(c.Workspace.Slug(), flow.WorkspaceSlug))
	authID, err := uuid.Parse(flow.AuthConfigID)
	if err != nil {
		return "", err
	}
	connID, err := uuid.Parse(flow.ConnectionID)
	if err != nil {
		return "", err
	}
	var a domain.AuthConfig
	var creds map[string]any
	err = s.read(ctx, c, func(sess db.Session) error {
		got, ok, err := s.d.Auth.Get(ctx, sess, authID)
		if err != nil {
			return err
		}
		if !ok {
			s.countOAuth("unknown", "failed:connection_gone")
			return oaHttpErr(400, "OAuth connection no longer exists")
		}
		a = got
		m := s.d.Secrets.Manager(sess, c.UserID)
		creds, err = s.exchangeCode(ctx, m, a, r.Code, flow.CodeVerifier)
		return err
	})
	var ex *exchangeError
	if errors.As(err, &ex) {
		s.countOAuth(s.oauthProvider(authConfigIssuer(a.Config)), "failed:"+ex.reason)
		return oaWithQuery(landing, [2]string{"oauth", "error"}, [2]string{"reason", ex.reason}), nil
	}
	if err != nil {
		return "", err
	}
	err = s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		key, err := s.storeCredentials(ctx, sess, c, a.ID, creds)
		if err != nil {
			return err
		}
		if err := s.d.Auth.SetSecretKey(ctx, sess, authID, key, s.d.Now()); err != nil {
			return err
		}
		if flow.Scopes != nil {
			cfg := make(map[string]any, len(a.Config)+1)
			for k, v := range a.Config {
				cfg[k] = v
			}
			cfg["scopes"] = flow.Scopes
			if err := s.d.Auth.Update(ctx, sess, authID, nil, nil, cfg, s.d.Now()); err != nil {
				return err
			}
		}
		if flow.TargetKind == kindMCPInstance {
			_, err := s.d.Instances.SetAuthConfig(ctx, sess, connID, &authID, s.d.Now())
			return err
		}
		if s.d.OAuthStore == nil {
			return &domain.Unavailable{Msg: "OAuth connect is not available"}
		}
		ok, err := s.d.OAuthStore.AttachConnectionAuth(ctx, sess, connID, authID, s.d.Now())
		if err == nil && !ok {
			err = domain.ErrConnectionNotFound()
		}
		return err
	})
	if err != nil {
		return "", err
	}
	s.d.Log.InfoContext(ctx, "OAuth connect complete", "target_kind", flow.TargetKind, "connection_id", flow.ConnectionID, "auth_config_id", a.ID)
	if flow.TargetKind == kindMCPInstance {
		s.VerifyInBackground(c.Workspace, connID)
	}
	s.countOAuth(s.oauthProvider(authConfigIssuer(a.Config)), "succeeded")
	if s.installURL(&a) != "" {
		return oaWithQuery(landing, [2]string{"oauth", "success"}, [2]string{"install", "1"}), nil
	}
	return oaWithQuery(landing, [2]string{"oauth", "success"}), nil
}

// exchangeError is OAuthCodeExchangeError: the reason the landing page reports.
type exchangeError struct{ reason string }

func (e *exchangeError) Error() string { return "oauth code exchange: " + e.reason }

// exchangeCode is complete_authorization without the write: the credentials
// with the tokens a PKCE code redeems.
func (s *Service) exchangeCode(ctx context.Context, m secretGetter, a domain.AuthConfig, code, verifier string) (map[string]any, error) {
	creds, err := oaLoadCredentials(ctx, m, a)
	var clientID, secret string
	if err == nil {
		clientID, secret, err = s.clientCredentials(ctx, m, a, creds, false)
	}
	var data map[string]any
	status := 0
	if err == nil {
		form := url.Values{
			"grant_type": {"authorization_code"}, "code": {code}, "redirect_uri": {s.OAuthCallbackURI()},
			"code_verifier": {verifier}, "client_id": {clientID},
		}
		data, status, err = s.tokenRequest(ctx, a, form, clientID, secret)
	}
	if err == nil && (status < 200 || status >= 300 || data == nil) {
		err = fmt.Errorf("token endpoint answered %d", status)
	}
	if err != nil {
		s.d.Log.WarnContext(ctx, "OAuth code exchange failed", "auth_config_id", a.ID, "error", err)
		return nil, &exchangeError{reason: "token_exchange_failed"}
	}
	access := oaPyStr(data["access_token"])
	if access == "" {
		s.d.Log.WarnContext(ctx, "OAuth code exchange returned no access token", "auth_config_id", a.ID, "error", oaFirstNonEmpty(oaPyStr(data["error"]), "no error given"))
		return nil, &exchangeError{reason: "no_access_token"}
	}
	creds["access_token"] = access
	creds["refresh_token"] = oaPyStr(data["refresh_token"])
	creds["token_type"] = oaFirstNonEmpty(oaPyStr(data["token_type"]), "bearer")
	if sc, ok := data["scope"]; ok && domain.Truthy(sc) {
		creds["scope"] = sc
	} else {
		creds["scope"] = ""
	}
	s.setExpiry(creds, data["expires_in"])
	return creds, nil
}

// OAuthConnectReady reports whether the connect flow's ports are wired.
func (s *Service) OAuthConnectReady() bool {
	return s.d.KV != nil && s.d.Out != nil && s.d.OAuthStore != nil
}

// OAuthASReady reports whether the Hydra-facing shim can reach Hydra.
func (s *Service) OAuthASReady() bool { return s.d.Out != nil }
