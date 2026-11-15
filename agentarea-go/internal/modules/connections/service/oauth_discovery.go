package service

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"slices"
	"sort"
	"strings"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
)

// oauthProfile is OAuthProfile: one authorization server as a connection uses it.
type oauthProfile struct {
	Provider              string
	AuthorizationEndpoint string
	TokenEndpoint         string
	ResourceOrigins       []string
	// Issuer is empty for a catalog template, which names endpoints instead.
	Issuer               string
	RegistrationEndpoint string
	Scopes               []string
	DefaultScopes        []string
	Resource             string
	OfflineAccess        bool
	AuthorizeParams      map[string]string
	AuthorizationScheme  string
	ClientAuthMethod     string
}

func oaNotOffered(scopes, offered []string) []string {
	var out []string
	for _, s := range scopes {
		if !slices.Contains(offered, s) {
			out = append(out, s)
		}
	}
	return out
}

func oaDedupe(items []string) []string {
	out := make([]string, 0, len(items))
	for _, s := range items {
		if !slices.Contains(out, s) {
			out = append(out, s)
		}
	}
	return out
}

// check is OAuthProfile.__post_init__: a default the server does not offer is refused.
func (p oauthProfile) check() error {
	if u := oaNotOffered(p.DefaultScopes, p.Scopes); len(u) > 0 {
		return errors.New("default scopes the server does not offer: " + strings.Join(u, ", "))
	}
	return nil
}

// requestedScopes is what a sign-in asks for: the pick, else the default.
func (p oauthProfile) requestedScopes(chosen []string, picked bool) ([]string, error) {
	if !picked {
		if len(p.DefaultScopes) > 0 {
			return p.DefaultScopes, nil
		}
		return p.Scopes, nil
	}
	c := oaDedupe(chosen)
	if len(c) == 0 {
		return nil, errors.New("pick at least one scope")
	}
	if u := oaNotOffered(c, p.Scopes); len(u) > 0 {
		return nil, errors.New("scopes the server does not offer: " + strings.Join(u, ", "))
	}
	return c, nil
}

// platformAppFor is platform_app_for: matched on the issuer, or for a
// template on both endpoints; the app must serve every resource origin.
func (s *Service) platformAppFor(p oauthProfile) *OAuthApp {
	var app *OAuthApp
	if p.Issuer != "" {
		app = s.d.Config.App(oaNormalizeIssuer(p.Issuer))
	} else {
		for i := range s.d.Config.OAuthApps {
			c := &s.d.Config.OAuthApps[i]
			if c.AuthorizationEndpoint == p.AuthorizationEndpoint && c.TokenEndpoint == p.TokenEndpoint {
				app = c
				break
			}
		}
	}
	if app == nil {
		return nil
	}
	for _, o := range p.ResourceOrigins {
		if !slices.Contains(app.ResourceOrigins, o) {
			return nil
		}
	}
	return app
}

// autoSource is auto_credential_source: platform app, then DCR, else none.
func (s *Service) autoSource(p oauthProfile) string {
	if s.platformAppFor(p) != nil {
		return "platform"
	}
	if p.RegistrationEndpoint != "" {
		return "dynamic"
	}
	return ""
}

// protocolAuthorizeParams are the parameters the authorize URL owns.
func protocolAuthorizeParams() []string {
	return []string{
		"client_id", "code_challenge", "code_challenge_method", "redirect_uri", "resource",
		"response_type", "scope", "state",
	}
}

// oaCheckedAuthorizeParams refuses extras that would replace a protocol parameter.
func oaCheckedAuthorizeParams(extra map[string]string) error {
	var reserved []string
	for _, k := range protocolAuthorizeParams() {
		if _, ok := extra[k]; ok {
			reserved = append(reserved, k)
		}
	}
	if len(reserved) > 0 {
		return errors.New("extra authorize params may not replace " + strings.Join(reserved, ", "))
	}
	return nil
}

const (
	oauthAuthorizeParamsKey = "agentarea:oauth_authorize_params"
	oauthScopesKey          = "agentarea:oauth_scopes"
)

func oaSpecMetadata(jsonSpec map[string]any) map[string]any {
	m, _ := jsonSpec["metadata"].(map[string]any)
	return m
}

// oaSpecAuthorizeParams is oauth_authorize_params.
func oaSpecAuthorizeParams(jsonSpec map[string]any) (map[string]string, error) {
	declared, ok := oaSpecMetadata(jsonSpec)[oauthAuthorizeParamsKey]
	if !ok || declared == nil {
		return map[string]string{}, nil
	}
	obj, ok := declared.(map[string]any)
	if !ok {
		return nil, errors.New(oauthAuthorizeParamsKey + " must be an object of strings")
	}
	params := make(map[string]string, len(obj))
	for k, v := range obj {
		s, ok := v.(string)
		if !ok {
			return nil, errors.New(oauthAuthorizeParamsKey + " must be an object of strings")
		}
		params[k] = s
	}
	if err := oaCheckedAuthorizeParams(params); err != nil {
		return nil, fmt.Errorf("%s: %w", oauthAuthorizeParamsKey, err)
	}
	return params, nil
}

// oaSpecDefaultScopes is oauth_default_scopes.
func oaSpecDefaultScopes(jsonSpec map[string]any) ([]string, error) {
	declared, ok := oaSpecMetadata(jsonSpec)[oauthScopesKey]
	if !ok || declared == nil {
		return nil, nil
	}
	list, ok := declared.([]any)
	if !ok || len(list) == 0 {
		return nil, errors.New(oauthScopesKey + " must be a non-empty list of scope strings")
	}
	out := make([]string, 0, len(list))
	for _, v := range list {
		s, ok := v.(string)
		if !ok || s == "" {
			return nil, errors.New(oauthScopesKey + " must be a non-empty list of scope strings")
		}
		out = append(out, s)
	}
	return oaDedupe(out), nil
}

// discoveryError is MCPOAuthDiscoveryError.
type discoveryError struct{ msg string }

func (e *discoveryError) Error() string { return e.msg }

// asMetadata is AuthServerMetadata (RFC 8414).
type asMetadata struct {
	Issuer                string
	AuthorizationEndpoint string
	TokenEndpoint         string
	RegistrationEndpoint  string
	ScopesSupported       []string
	Resource              string
	OfflineAccess         bool
}

func oaLoopbackHosts() []string { return []string{"localhost", "127.0.0.1", "::1"} }

// oaValidateEndpointURL refuses an AS endpoint that is not https (or http to loopback).
func oaValidateEndpointURL(raw, field string) (string, error) {
	u, err := url.Parse(raw)
	if err != nil || (u.Scheme != "https" && !slices.Contains(oaLoopbackHosts(), u.Hostname())) {
		return "", &discoveryError{fmt.Sprintf("Authorization server %s '%s' must use https (or http on a loopback host for local development)", field, raw)}
	}
	return raw, nil
}

func oaStringList(v any) []string {
	l, _ := v.([]any)
	out := []string{}
	for _, x := range l {
		if s, ok := x.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

// oaAsMetadataFrom is _as_metadata_from: nil when the document lacks both endpoints.
func oaAsMetadataFrom(data map[string]any, asBase string) (*asMetadata, error) {
	authz, ok1 := data["authorization_endpoint"].(string)
	token, ok2 := data["token_endpoint"].(string)
	if data == nil || !ok1 || !ok2 {
		return nil, nil
	}
	m := &asMetadata{Issuer: asBase}
	if iss, ok := data["issuer"].(string); ok && iss != "" {
		m.Issuer = iss
	}
	var err error
	if m.AuthorizationEndpoint, err = oaValidateEndpointURL(authz, "authorization_endpoint"); err != nil {
		return nil, err
	}
	if m.TokenEndpoint, err = oaValidateEndpointURL(token, "token_endpoint"); err != nil {
		return nil, err
	}
	if reg, ok := data["registration_endpoint"].(string); ok && reg != "" {
		if m.RegistrationEndpoint, err = oaValidateEndpointURL(reg, "registration_endpoint"); err != nil {
			return nil, err
		}
	}
	m.ScopesSupported = oaStringList(data["scopes_supported"])
	m.OfflineAccess = slices.Contains(m.ScopesSupported, "offline_access")
	return m, nil
}

func oaParseResourceMetadataURL(header string) string {
	result := ""
	for _, part := range strings.Split(header, ",") {
		part = strings.TrimSpace(part)
		if _, v, ok := strings.Cut(part, "resource_metadata="); ok {
			result = strings.Trim(strings.TrimSpace(v), `"`)
		}
	}
	return result
}

func oaParseScopeHint(header string) string {
	for _, part := range strings.Split(header, ",") {
		if _, v, ok := strings.Cut(strings.TrimSpace(part), "scope="); ok {
			return strings.Trim(strings.TrimSpace(v), `"`)
		}
	}
	return ""
}

func oaAsMetadataURLs(issuer string) []string {
	u, err := url.Parse(strings.TrimRight(issuer, "/"))
	if err != nil {
		return nil
	}
	origin := u.Scheme + "://" + u.Host
	if u.Path == "" {
		return []string{origin + "/.well-known/oauth-authorization-server", origin + "/.well-known/openid-configuration"}
	}
	return []string{
		origin + "/.well-known/oauth-authorization-server" + u.Path,
		origin + "/.well-known/openid-configuration" + u.Path,
		origin + u.Path + "/.well-known/openid-configuration",
	}
}

func (s *Service) getJSON(ctx context.Context, c *http.Client, raw string) (int, map[string]any, bool, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, raw, nil)
	if err != nil {
		return 0, nil, false, err
	}
	resp, err := c.Do(req)
	if err != nil {
		return 0, nil, false, err
	}
	defer func() { _ = resp.Body.Close() }()
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxOAuthBody))
	if err != nil {
		return resp.StatusCode, nil, false, err
	}
	var v any
	dec := json.NewDecoder(strings.NewReader(string(body)))
	dec.UseNumber()
	if err := dec.Decode(&v); err != nil {
		return resp.StatusCode, nil, false, nil
	}
	m, isObj := v.(map[string]any)
	return resp.StatusCode, m, isObj, nil
}

// discoverAuthServer is discover_auth_server: RFC 9728 then RFC 8414. Every
// failure is a *discoveryError.
func (s *Service) discoverAuthServer(ctx context.Context, mcpURL string) (*asMetadata, error) {
	m, err := s.discover(ctx, mcpURL)
	var de *discoveryError
	if err != nil && !errors.As(err, &de) {
		return nil, &discoveryError{fmt.Sprintf("Could not reach %s: %v", mcpURL, err)}
	}
	return m, err
}

func (s *Service) discover(ctx context.Context, mcpURL string) (*asMetadata, error) {
	follow := s.httpClient(netguard.Member, discoveryTimeout, true)
	c := s.httpClient(netguard.Member, discoveryTimeout, false)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, mcpURL, nil)
	if err != nil {
		return nil, err
	}
	resp, err := follow.Do(req)
	if err != nil {
		return nil, err
	}
	_ = resp.Body.Close()
	challenge := resp.Header.Get("WWW-Authenticate")
	metaURL := oaParseResourceMetadataURL(challenge)
	hint := oaParseScopeHint(challenge)
	u, err := url.Parse(mcpURL)
	if err != nil {
		return nil, err
	}
	root := u.Scheme + "://" + u.Host + "/.well-known/oauth-protected-resource"
	if metaURL == "" {
		metaURL = root + strings.TrimRight(u.Path, "/")
	}
	status, pr, isObj, err := s.getJSON(ctx, c, metaURL)
	if err != nil {
		return nil, err
	}
	if (status == 401 || status == 403 || status == 404) && root != metaURL {
		if status, pr, isObj, err = s.getJSON(ctx, c, root); err != nil {
			return nil, err
		}
	}
	if status != http.StatusOK {
		return nil, &discoveryError{fmt.Sprintf("Could not fetch OAuth protected-resource metadata for %s (HTTP %d). The server may not support automated OAuth discovery.", mcpURL, status)}
	}
	if pr == nil && !isObj {
		return nil, &discoveryError{fmt.Sprintf("OAuth protected-resource metadata at %s is not an object. The server may not support automated OAuth discovery.", metaURL)}
	}
	resource := mcpURL
	if r, ok := pr["resource"]; ok && r != nil && r != "" {
		rs, ok := r.(string)
		if !ok {
			return nil, &discoveryError{fmt.Sprintf("OAuth protected-resource metadata at %s has a resource that is not a string.", metaURL)}
		}
		resource = rs
	}
	servers, _ := pr["authorization_servers"].([]any)
	if len(servers) == 0 {
		if v, ok := pr["authorization_servers"]; ok && v != nil && !oaIsEmptyJSON(v) {
			return nil, &discoveryError{fmt.Sprintf("authorization_servers in protected resource metadata at %s is not a list of URLs.", metaURL)}
		}
		return nil, &discoveryError{fmt.Sprintf("No authorization_servers in protected resource metadata at %s", metaURL)}
	}
	first, ok := servers[0].(string)
	if !ok || strings.TrimSpace(first) == "" {
		return nil, &discoveryError{fmt.Sprintf("authorization_servers in protected resource metadata at %s is not a list of URLs.", metaURL)}
	}
	asBase := strings.TrimRight(first, "/")
	meta, err := s.fetchASMetadata(ctx, c, asBase)
	if err != nil {
		return nil, err
	}
	meta.Resource = resource
	if rs := oaStringList(pr["scopes_supported"]); len(rs) > 0 {
		meta.ScopesSupported = rs
	} else if hint != "" {
		meta.ScopesSupported = strings.Fields(hint)
	}
	return meta, nil
}

func oaIsEmptyJSON(v any) bool {
	switch t := v.(type) {
	case string:
		return t == ""
	case []any:
		return len(t) == 0
	case map[string]any:
		return len(t) == 0
	case bool:
		return !t
	}
	return false
}

func (s *Service) fetchASMetadata(ctx context.Context, c *http.Client, asBase string) (*asMetadata, error) {
	urls := oaAsMetadataURLs(asBase)
	for _, u := range urls {
		status, data, _, err := s.getJSON(ctx, c, u)
		if err != nil || status != http.StatusOK || data == nil {
			continue
		}
		m, err := oaAsMetadataFrom(data, asBase)
		if err != nil {
			return nil, err
		}
		if m != nil {
			return m, nil
		}
	}
	return nil, &discoveryError{fmt.Sprintf("Could not fetch AS metadata from %s (tried %s)", asBase, strings.Join(urls, ", "))}
}

// oaDiscoveredProfile is discovered_profile: tokens go to the MCP URL's origin.
func oaDiscoveredProfile(m *asMetadata, mcpURL string, params map[string]string, defaults []string) (oauthProfile, error) {
	scopes := m.ScopesSupported
	if len(scopes) == 0 {
		scopes = defaults
	}
	p := oauthProfile{
		Provider: "mcp-remote", Issuer: m.Issuer, AuthorizationEndpoint: m.AuthorizationEndpoint,
		TokenEndpoint: m.TokenEndpoint, RegistrationEndpoint: m.RegistrationEndpoint,
		Scopes: scopes, DefaultScopes: defaults, Resource: m.Resource, OfflineAccess: m.OfflineAccess,
		ResourceOrigins: []string{oaUrlOrigin(mcpURL)}, AuthorizeParams: params,
		AuthorizationScheme: "Bearer", ClientAuthMethod: "client_secret_post",
	}
	if err := p.check(); err != nil {
		return oauthProfile{}, fmt.Errorf("%s: %w", oauthScopesKey, err)
	}
	return p, nil
}

// registerClient is register_client (RFC 7591): a public PKCE client per authorization.
func (s *Service) registerClient(ctx context.Context, endpoint, redirectURI string) (string, string, error) {
	if endpoint == "" {
		return "", "", &discoveryError{"Authorization server does not support Dynamic Client Registration (no registration_endpoint). Pre-registered credentials required."}
	}
	payload, err := json.Marshal(map[string]any{
		"client_name": "AgentArea", "redirect_uris": []string{redirectURI},
		"grant_types": []string{"authorization_code"}, "response_types": []string{"code"},
		"token_endpoint_auth_method": "none", "application_type": "web",
	})
	if err != nil {
		return "", "", err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, strings.NewReader(string(payload)))
	if err != nil {
		return "", "", err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := s.httpClient(netguard.Member, discoveryTimeout, false).Do(req)
	if err != nil {
		return "", "", err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", "", fmt.Errorf("registration answered HTTP %d", resp.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxOAuthBody))
	if err != nil {
		return "", "", err
	}
	data, err := oaDecodeObject(body)
	if err != nil {
		return "", "", err
	}
	id, ok := data["client_id"].(string)
	if !ok || id == "" {
		return "", "", errors.New("registration returned no client_id")
	}
	secret, _ := data["client_secret"].(string)
	return id, secret, nil
}

// oaPkcePair is PKCEPair.generate: a 64-byte token_urlsafe verifier and its S256 challenge.
func oaPkcePair() (string, string) {
	verifier := oaTokenURLSafe(64)
	sum := sha256.Sum256([]byte(verifier))
	return verifier, base64.RawURLEncoding.EncodeToString(sum[:])
}

// oaTokenURLSafe is secrets.token_urlsafe(n).
func oaTokenURLSafe(n int) string {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	return base64.RawURLEncoding.EncodeToString(b)
}

// oaAuthorizeURL is build_authorize_url: OAuth 2.1 + PKCE, the resource
// indicator, offline_access when the server lists it, then the extras.
func oaAuthorizeURL(p oauthProfile, clientID, redirectURI, challenge, state string, scopes []string) string {
	list := slices.Clone(scopes)
	if len(list) == 0 {
		list = slices.Clone(p.Scopes)
	}
	if p.OfflineAccess && !slices.Contains(list, "offline_access") {
		list = append(list, "offline_access")
	}
	pairs := [][2]string{
		{"response_type", "code"}, {"client_id", clientID}, {"redirect_uri", redirectURI},
		{"state", state}, {"code_challenge", challenge}, {"code_challenge_method", "S256"},
	}
	if len(list) > 0 {
		pairs = append(pairs, [2]string{"scope", strings.Join(list, " ")})
	}
	if p.Resource != "" {
		pairs = append(pairs, [2]string{"resource", p.Resource})
	}
	keys := make([]string, 0, len(p.AuthorizeParams))
	for k := range p.AuthorizeParams {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		pairs = append(pairs, [2]string{k, p.AuthorizeParams[k]})
	}
	parts := make([]string, len(pairs))
	for i, kv := range pairs {
		parts[i] = url.QueryEscape(kv[0]) + "=" + url.QueryEscape(kv[1])
	}
	return p.AuthorizationEndpoint + "?" + strings.Join(parts, "&")
}
