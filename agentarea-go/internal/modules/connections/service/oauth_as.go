package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"slices"
	"sort"
	"strings"
	"sync"
	"time"

	"golang.org/x/sync/singleflight"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
)

// hydraDiscoveryTTL is how long a fetched discovery document of Hydra is
// served to the anonymous metadata routes.
const hydraDiscoveryTTL = 5 * time.Minute

// hydraDiscoveryCache is the last discovery document Hydra served; a failed
// fetch is not kept, concurrent fetches share one request.
type hydraDiscoveryCache struct {
	flight    singleflight.Group
	mu        sync.Mutex
	doc       wirejson.Object
	fetchedAt time.Time
}

const oaUuidPattern = `[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}`

var (
	perURLResource = regexp.MustCompile(`^(?:mcp/w/(?:[a-z0-9-]{1,120}|` + oaUuidPattern + `)|(?:mcp/clients|client-mcp)/` + oaUuidPattern + `)$`)
	safeOAuth2Path = regexp.MustCompile(`^[A-Za-z0-9._~/-]+$`)
)

func proxiedEndpoint() []string {
	return []string{"authorization_endpoint", "token_endpoint", "revocation_endpoint", "jwks_uri"}
}

func dcrFields() []string {
	return []string{
		"client_name", "client_uri", "logo_uri", "policy_uri", "tos_uri", "contacts", "redirect_uris",
		"token_endpoint_auth_method", "audience", "response_types", "grant_types", "scope", "skip_consent",
	}
}

func dcrAuthMethods() []string { return []string{"client_secret_basic", "client_secret_post", "none"} }

// IsProtectedResource is _is_protected_resource: the MCP endpoints this API protects.
func IsProtectedResource(path string) bool {
	return path == "mcp" || path == "client-mcp" || perURLResource.MatchString(path)
}

// SafeOAuth2Path is _is_safe_oauth2_subpath: OAuth2-style identifiers, no parent traversal.
func SafeOAuth2Path(path string) bool {
	return path != "" && safeOAuth2Path.MatchString(path) && !slices.Contains(strings.Split(path, "/"), "..")
}

func (s *Service) hydraURL() string { return strings.TrimRight(s.d.Config.HydraURL, "/") }

func (s *Service) apiBase() string { return strings.TrimRight(s.d.APIURL, "/") }

func (s *Service) internalClient(timeout time.Duration) *http.Client {
	return s.httpClient(netguard.Internal, timeout, false)
}

func (s *Service) fetchHydraDiscovery(ctx context.Context, timeout time.Duration) (wirejson.Object, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, s.hydraURL()+"/.well-known/openid-configuration", nil)
	if err != nil {
		return nil, err
	}
	resp, err := s.internalClient(timeout).Do(req)
	if err != nil {
		return nil, err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("hydra discovery answered %d", resp.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxOAuthBody))
	if err != nil {
		return nil, err
	}
	v, err := wirejson.Unmarshal(body)
	if err != nil {
		return nil, err
	}
	doc, ok := v.(wirejson.Object)
	if !ok {
		return nil, errors.New("hydra discovery is not an object")
	}
	return doc, nil
}

// cachedHydraDiscovery is Hydra's discovery document, fetched at most once
// per hydraDiscoveryTTL. The document is shared: callers copy before changing it.
func (s *Service) cachedHydraDiscovery(ctx context.Context) (wirejson.Object, error) {
	c := &s.discovery
	now := s.d.Now()
	c.mu.Lock()
	if c.doc != nil && now.Sub(c.fetchedAt) < hydraDiscoveryTTL {
		doc := c.doc
		c.mu.Unlock()
		return doc, nil
	}
	c.mu.Unlock()
	ch := c.flight.DoChan("discovery", func() (any, error) {
		doc, err := s.fetchHydraDiscovery(context.WithoutCancel(ctx), 5*time.Second)
		if err != nil {
			return nil, err
		}
		c.mu.Lock()
		c.doc, c.fetchedAt = doc, now
		c.mu.Unlock()
		return doc, nil
	})
	select {
	case r := <-ch:
		if r.Err != nil {
			return nil, r.Err
		}
		return r.Val.(wirejson.Object), nil
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

// hydraDiscovery is _hydra_discovery: nil when unreachable.
func (s *Service) hydraDiscovery(ctx context.Context) wirejson.Object {
	doc, err := s.cachedHydraDiscovery(ctx)
	if err != nil {
		s.d.Log.InfoContext(ctx, "Hydra discovery unavailable", "error", err)
		return nil
	}
	return doc
}

// ProtectedResource is RFC 9728 metadata for the resource path: Hydra is the
// authorization server when it advertises registration, else this API.
func (s *Service) ProtectedResource(ctx context.Context, resourcePath string) wirejson.Object {
	doc := s.hydraDiscovery(ctx)
	asURL := s.apiBase()
	issuer, _ := oaGetStr(doc, "issuer")
	issuer = strings.TrimRight(issuer, "/")
	if reg, ok := doc.Get("registration_endpoint"); issuer != "" && ok && oaTruthyJSON(reg) {
		asURL = issuer
	}
	scopes := make([]any, len(s.d.Config.OAuthScopes))
	for i, sc := range s.d.Config.OAuthScopes {
		scopes[i] = sc
	}
	return wirejson.Object{
		{Key: "resource", Value: s.apiBase() + "/" + resourcePath},
		{Key: "authorization_servers", Value: []any{asURL}},
		{Key: "scopes_supported", Value: scopes},
		{Key: "bearer_methods_supported", Value: []any{"header"}},
	}
}

func oaGetStr(o wirejson.Object, key string) (string, bool) {
	v, ok := o.Get(key)
	if !ok {
		return "", false
	}
	str, ok := v.(string)
	return str, ok
}

func oaTruthyJSON(v any) bool {
	switch t := v.(type) {
	case nil:
		return false
	case string:
		return t != ""
	case bool:
		return t
	case []any:
		return len(t) > 0
	case wirejson.Object:
		return len(t) > 0
	}
	return true
}

// AuthorizationServerMetadata is Hydra's document with the endpoints this API
// proxies rewritten to it, issuer this API, registration our DCR proxy.
func (s *Service) AuthorizationServerMetadata(ctx context.Context) (wirejson.Object, error) {
	doc, err := s.cachedHydraDiscovery(ctx)
	if err != nil {
		return nil, err
	}
	hydra := s.hydraURL()
	issuer, ok := oaGetStr(doc, "issuer")
	if !ok {
		issuer = hydra
	}
	issuer = strings.TrimRight(issuer, "/")
	rewrite := func(raw string) string {
		for _, prefix := range []string{issuer, hydra} {
			if prefix != "" && strings.HasPrefix(raw, prefix) {
				return s.apiBase() + raw[len(prefix):]
			}
		}
		return raw
	}
	out := slices.Clone(doc)
	for _, f := range proxiedEndpoint() {
		if v, ok := out.Get(f); ok {
			if str, isStr := v.(string); isStr && str != "" {
				out.Set(f, rewrite(str))
			}
		}
	}
	out.Set("issuer", s.apiBase())
	out.Set("registration_endpoint", s.apiBase()+"/oauth2/register")
	return out, nil
}

// HydraAuthorizeURL is where the browser goes for /oauth2/auth.
func (s *Service) HydraAuthorizeURL(rawQuery string) string {
	target := strings.TrimRight(s.d.Config.HydraBrowserURL, "/") + "/oauth2/auth"
	if rawQuery != "" {
		target += "?" + rawQuery
	}
	return target
}

// DCRRefusal is a registration the proxy refuses: 400 with an OAuth error body.
type DCRRefusal struct {
	Code        string
	Description string
}

func (e *DCRRefusal) Error() string { return e.Code + ": " + e.Description }

// Registration is a DCR request shaped for Hydra's admin API: the
// security-relevant fields forced, only the descriptive ones forwarded.
func (s *Service) Registration(body []byte) (map[string]any, error) {
	var data map[string]any
	if v, err := oaDecodeAny(body); err == nil {
		m, ok := v.(map[string]any)
		if !ok {
			return nil, &DCRRefusal{"invalid_client_metadata", "the registration request must be a JSON object"}
		}
		data = m
	}
	if data == nil {
		data = map[string]any{}
	}
	delete(data, "client_id")
	delete(data, "client_secret")
	data["audience"] = []any{s.apiBase()}
	data["response_types"] = []any{"code"}
	data["skip_consent"] = false

	allowed := []string{"authorization_code", "refresh_token"}
	var requested []string
	if raw, ok := data["grant_types"]; ok && oaTruthyAny(raw) {
		l, isList := raw.([]any)
		if !isList {
			return nil, &DCRRefusal{"invalid_client_metadata", fmt.Sprintf("grant_types must be a subset of %s", oaPyList(allowed))}
		}
		for _, g := range l {
			if str, ok := g.(string); ok {
				requested = append(requested, str)
			}
		}
		if len(l) > 0 && !slices.ContainsFunc(allowed, func(g string) bool { return slices.Contains(requested, g) }) {
			return nil, &DCRRefusal{"invalid_client_metadata", fmt.Sprintf("grant_types must be a subset of %s", oaPyList(allowed))}
		}
	}
	var granted []any
	for _, g := range allowed {
		if slices.Contains(requested, g) {
			granted = append(granted, g)
		}
	}
	if len(granted) == 0 {
		granted = []any{"authorization_code", "refresh_token"}
	}
	data["grant_types"] = granted

	offered := oaDedupe(s.d.Config.OAuthScopes)
	asked := strings.Fields(oaPyStr(data["scope"]))
	var scopes []string
	if len(asked) == 0 {
		scopes = slices.Clone(offered)
	} else {
		for _, sc := range oaDedupe(asked) {
			if slices.Contains(offered, sc) {
				scopes = append(scopes, sc)
			}
		}
	}
	if len(scopes) == 0 {
		sorted := slices.Clone(offered)
		sort.Strings(sorted)
		return nil, &DCRRefusal{"invalid_client_metadata", "none of the requested scopes are offered by this server; available: " + oaPyList(sorted)}
	}
	sort.Strings(scopes)
	data["scope"] = strings.Join(scopes, " ")

	uris, _ := data["redirect_uris"].([]any)
	if raw, ok := data["redirect_uris"]; ok && oaTruthyAny(raw) && uris == nil {
		if str, isStr := raw.(string); isStr {
			for _, r := range str {
				uris = append(uris, string(r))
			}
		} else {
			uris = []any{raw}
		}
	}
	if len(uris) == 0 {
		return nil, &DCRRefusal{"invalid_redirect_uri", "redirect_uris is required"}
	}
	for _, raw := range uris {
		s := oaPyStr(raw)
		u, err := url.Parse(s)
		loopback := err == nil && u.Scheme == "http" && slices.Contains(oaLoopbackHosts(), u.Hostname())
		if err != nil && strings.HasPrefix(s, "https://") {
			return nil, &DCRRefusal{"invalid_redirect_uri", "redirect_uris must name one host, with no wildcard, credentials or fragment"}
		}
		if err != nil || (u.Scheme != "https" && !loopback) {
			return nil, &DCRRefusal{"invalid_redirect_uri", "redirect_uris must use https, or http to a loopback host for native clients"}
		}
		// The consent screen names the host the code goes to; a wildcard,
		// credentials or a fragment would make it another host than the one read.
		if u.Hostname() == "" || strings.Contains(u.Host, "*") || u.User != nil || u.Fragment != "" || strings.Contains(s, "#") {
			return nil, &DCRRefusal{"invalid_redirect_uri", "redirect_uris must name one host, with no wildcard, credentials or fragment"}
		}
	}
	if _, ok := data["client_uri"]; !ok {
		data["client_uri"] = s.apiBase()
	}
	if !oaTruthyAny(data["contacts"]) {
		data["contacts"] = []any{}
	}
	if m, ok := data["token_endpoint_auth_method"]; ok && m != nil {
		str, isStr := m.(string)
		if !isStr || !slices.Contains(dcrAuthMethods(), str) {
			return nil, &DCRRefusal{"invalid_client_metadata", "token_endpoint_auth_method must be one of " + oaPyList(dcrAuthMethods())}
		}
	}
	out := make(map[string]any, len(dcrFields()))
	for _, f := range dcrFields() {
		if v, ok := data[f]; ok {
			out[f] = v
		}
	}
	return out, nil
}

func oaDecodeAny(b []byte) (any, error) {
	var v any
	dec := json.NewDecoder(strings.NewReader(string(b)))
	dec.UseNumber()
	err := dec.Decode(&v)
	return v, err
}

func oaTruthyAny(v any) bool {
	switch t := v.(type) {
	case nil:
		return false
	case string:
		return t != ""
	case bool:
		return t
	case []any:
		return len(t) > 0
	case map[string]any:
		return len(t) > 0
	case json.Number:
		return t.String() != "0"
	}
	return true
}

// oaPyList is repr(list of str).
func oaPyList(items []string) string {
	parts := make([]string, len(items))
	for i, it := range items {
		parts[i] = "'" + it + "'"
	}
	return "[" + strings.Join(parts, ", ") + "]"
}

// RegisterClient posts a shaped registration to Hydra's admin API and
// returns its status and body as they came.
func (s *Service) RegisterClient(ctx context.Context, registration map[string]any) (int, []byte, error) {
	raw, err := json.Marshal(registration)
	if err != nil {
		return 0, nil, err
	}
	target := strings.TrimRight(s.d.Config.HydraAdminURL, "/") + "/admin/clients"
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, target, strings.NewReader(string(raw)))
	if err != nil {
		return 0, nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := s.internalClient(15 * time.Second).Do(req)
	if err != nil {
		return 0, nil, err
	}
	defer func() { _ = resp.Body.Close() }()
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxOAuthBody))
	return resp.StatusCode, body, err
}

// HydraProxy forwards a request to Hydra's public URL at path (already
// checked by SafeOAuth2Path when it is an /oauth2/ subpath).
func (s *Service) HydraProxy(ctx context.Context, method, path, rawQuery string, header http.Header, body io.Reader, timeout time.Duration) (*http.Response, error) {
	target := s.hydraURL() + path
	if rawQuery != "" {
		target += "?" + rawQuery
	}
	req, err := http.NewRequestWithContext(ctx, method, target, body)
	if err != nil {
		return nil, err
	}
	for k, vs := range header {
		if strings.EqualFold(k, "Host") || strings.EqualFold(k, "Content-Length") {
			continue
		}
		req.Header[k] = slices.Clone(vs)
	}
	return s.internalClient(timeout).Do(req)
}
