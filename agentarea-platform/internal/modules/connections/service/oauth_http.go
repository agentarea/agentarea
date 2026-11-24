package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
)

type secretGetter = ksecrets.Manager

var errSecretNotFound = ksecrets.ErrNotFound

const (
	tokenTimeout     = 10 * time.Second
	discoveryTimeout = 15 * time.Second
	maxOAuthBody     = 1 << 20
)

// oaLoadCredentials is _load_credentials: none without a secret key, an error
// when the key names a secret that is gone.
func oaLoadCredentials(ctx context.Context, m secretGetter, a domain.AuthConfig) (map[string]any, error) {
	if a.SecretKey == nil || *a.SecretKey == "" {
		return map[string]any{}, nil
	}
	raw, err := m.Get(ctx, *a.SecretKey)
	if errors.Is(err, errSecretNotFound) {
		return nil, &domain.Invalid{Msg: fmt.Sprintf("Auth config %s references a secret that no longer exists. Re-enter its credentials.", a.ID)}
	}
	if err != nil {
		return nil, err
	}
	creds, err := oaDecodeObject([]byte(raw))
	if err != nil {
		return nil, fmt.Errorf("auth config %s credentials: %w", a.ID, err)
	}
	if creds == nil {
		creds = map[string]any{}
	}
	return creds, nil
}

func oaMarshalCreds(creds map[string]any) (string, error) {
	raw, err := json.Marshal(creds)
	return string(raw), err
}

// oaDecodeObject is a JSON object with numbers kept as written; nil for any other JSON value.
func oaDecodeObject(b []byte) (map[string]any, error) {
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	m, _ := v.(map[string]any)
	return m, nil
}

// oaPyStr is str(value or "") for the JSON values a config holds.
func oaPyStr(v any) string {
	switch t := v.(type) {
	case nil:
		return ""
	case string:
		return t
	case json.Number:
		return t.String()
	case bool:
		if t {
			return "True"
		}
		return ""
	}
	return fmt.Sprint(v)
}

func oaPyFloat(v any) (float64, bool) {
	switch t := v.(type) {
	case json.Number:
		f, err := t.Float64()
		return f, err == nil
	case float64:
		return t, true
	case int:
		return float64(t), true
	case int64:
		return float64(t), true
	case string:
		f, err := strconv.ParseFloat(strings.TrimSpace(t), 64)
		return f, err == nil
	}
	return 0, false
}

// oaPyInt is int(value): integers, floats truncated, integer strings; bools count.
func oaPyInt(v any) (int64, bool) {
	switch t := v.(type) {
	case json.Number:
		if n, err := t.Int64(); err == nil {
			return n, true
		}
		f, err := t.Float64()
		if err != nil || math.IsInf(f, 0) || math.IsNaN(f) {
			return 0, false
		}
		return int64(f), true
	case float64:
		return int64(t), true
	case int:
		return int64(t), true
	case int64:
		return t, true
	case bool:
		if t {
			return 1, true
		}
		return 0, true
	case string:
		n, err := strconv.ParseInt(strings.TrimSpace(t), 10, 64)
		return n, err == nil
	}
	return 0, false
}

// oaUrlOrigin is url_origin: scheme://host[:port], "" when the URL has none.
func oaUrlOrigin(raw string) string {
	u, err := url.Parse(raw)
	if err != nil || u.Scheme == "" || u.Host == "" {
		return ""
	}
	return u.Scheme + "://" + u.Host
}

func oaNormalizeIssuer(issuer string) string {
	return strings.TrimRight(strings.TrimSpace(issuer), "/")
}

// httpClient is the outbound client to member-supplied OAuth endpoints;
// follow says whether redirects are followed (httpx does not by default).
func (s *Service) httpClient(dest netguard.Destination, timeout time.Duration, follow bool) *http.Client {
	c := &http.Client{Transport: s.d.Out.Transport(dest), Timeout: timeout}
	if !follow {
		c.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	}
	return c
}

// tokenEndpoint is where a config's codes and refresh tokens are redeemed:
// a platform app's own endpoint, never the config's copy.
func (s *Service) tokenEndpoint(a domain.AuthConfig) (string, error) {
	app, err := s.platformApp(a)
	if err != nil {
		return "", err
	}
	if app != nil {
		return app.TokenEndpoint, nil
	}
	return oaPyStr(a.Config["token_url"]), nil
}

// tokenRequest is _token_request: the grant POSTed as a form, the client
// authenticated its way. data is the decoded 2xx object (nil when the body
// is not one); a transport failure is an error.
func (s *Service) tokenRequest(ctx context.Context, a domain.AuthConfig, form url.Values, clientID, secret string) (map[string]any, int, error) {
	endpoint, err := s.tokenEndpoint(a)
	if err != nil {
		return nil, 0, err
	}
	if endpoint == "" || clientID == "" {
		return nil, 0, &domain.Invalid{Msg: "oauth2 config missing token_url or client_id"}
	}
	basic := a.Config["client_auth_method"] == "client_secret_basic"
	if basic && secret == "" {
		return nil, 0, &domain.Invalid{Msg: fmt.Sprintf("Auth config %s authenticates with client_secret_basic but has no client secret.", a.ID)}
	}
	if !basic && secret != "" {
		form.Set("client_secret", secret)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, strings.NewReader(form.Encode()))
	if err != nil {
		return nil, 0, netguard.SafeURLError(err)
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Accept", "application/json")
	if basic {
		req.SetBasicAuth(clientID, secret)
	}
	resp, err := s.httpClient(netguard.Member, tokenTimeout, false).Do(req)
	if err != nil {
		return nil, 0, netguard.SafeURLError(err)
	}
	defer func() { _ = resp.Body.Close() }()
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxOAuthBody))
	if err != nil {
		return nil, resp.StatusCode, err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, resp.StatusCode, nil
	}
	data, err := oaDecodeObject(body)
	if err != nil {
		return nil, resp.StatusCode, nil
	}
	return data, resp.StatusCode, nil
}
