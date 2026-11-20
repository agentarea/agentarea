package authn

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"slices"
	"strings"
	"sync"
	"time"

	"golang.org/x/sync/singleflight"

	port "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
)

// PyJWKClient's defaults, which the Python client keeps.
const (
	hydraJWKSLifespan      = 300 * time.Second
	hydraJWKSCooldown      = 30 * time.Second
	hydraJWKSTimeout       = 30 * time.Second
	hydraUnavailableLogGap = 600 * time.Second
	hydraJWKSMaxBody       = 1 << 20
)

const detailHydraIssuer = "Token was not issued by this API's authorization server"

const (
	detailHydraNoGrant     = "OAuth token grants no access to this API; sign in again"
	detailHydraNoWorkspace = "OAuth token names no workspace"
)

// hydra verifies Hydra-issued OAuth JWTs against Hydra's JWKS
// (dependencies.py _try_hydra_token, PyJWKClient), and, unlike Python, their
// iss against the issuer Hydra's discovery document names, fetched and cached
// with the JWKS. Unlike PyJWKClient with
// cache_keys=True, a key is not remembered after it leaves the JWKS. Unlike
// PyJWKClient, a token whose header does not parse never causes a fetch, a
// failed fetch is not retried within the cooldown, and concurrent fetches
// share one request made outside the lock.
type hydra struct {
	jwksURL      string
	discoveryURL string
	audience     string
	challenge    string
	client       *http.Client
	log          *slog.Logger
	fetches      singleflight.Group

	mu        sync.Mutex
	keys      []jwk
	issuer    string
	cachedAt  time.Time
	lastFetch time.Time
	failedAt  time.Time
	failure   error

	logMu         sync.Mutex
	lastUnavailLg time.Time
}

func newHydra(cfg Config, client *http.Client, log *slog.Logger) *hydra {
	base := strings.TrimRight(cfg.HydraURL, "/")
	return &hydra{
		jwksURL:      base + "/.well-known/jwks.json",
		discoveryURL: base + "/.well-known/openid-configuration",
		audience:     cfg.HydraAudience,
		challenge:    port.Challenge(cfg.APIURL),
		client:       client,
		log:          log,
	}
}

// newJWKSClient fetches without following redirects, as PyJWKClient does.
func newJWKSClient() *http.Client {
	return &http.Client{
		Timeout: hydraJWKSTimeout,
		CheckRedirect: func(*http.Request, []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}
}

func (h *hydra) get(ctx context.Context, url string) (any, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	resp, err := h.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		return nil, fmt.Errorf("fail to fetch data from the url: HTTP %d", resp.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, hydraJWKSMaxBody))
	if err != nil {
		return nil, err
	}
	return loadJSON(body)
}

// fetch reads Hydra's issuer from its discovery document, then its JWKS.
func (h *hydra) fetch(ctx context.Context) ([]jwk, string, error) {
	doc, err := h.get(ctx, h.discoveryURL)
	if err != nil {
		return nil, "", err
	}
	obj, _ := doc.(map[string]any)
	issuer, _ := obj["issuer"].(string)
	if issuer == "" {
		return nil, "", errors.New("hydra's discovery document names no issuer")
	}
	data, err := h.get(ctx, h.jwksURL)
	if err != nil {
		return nil, "", err
	}
	keys, err := signingKeys(data)
	if err != nil {
		return nil, "", err
	}
	return keys, issuer, nil
}

// signingKeys is get_signing_keys: the cached set while fresh, else a fetch.
// With refresh, the cached set is kept within the cooldown of the last
// successful fetch. A failure is answered from memory for the cooldown.
func (h *hydra) signingKeys(ctx context.Context, now time.Time, refresh bool) ([]jwk, error) {
	h.mu.Lock()
	switch {
	case !refresh && h.keys != nil && now.Sub(h.cachedAt) <= hydraJWKSLifespan,
		refresh && h.keys != nil && now.Sub(h.lastFetch) < hydraJWKSCooldown:
		keys := h.keys
		h.mu.Unlock()
		return keys, nil
	case h.failure != nil && now.Sub(h.failedAt) < hydraJWKSCooldown:
		err := h.failure
		h.mu.Unlock()
		return nil, err
	}
	h.mu.Unlock()
	ch := h.fetches.DoChan("jwks", func() (any, error) {
		fctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), hydraJWKSTimeout)
		defer cancel()
		keys, issuer, err := h.fetch(fctx)
		h.mu.Lock()
		defer h.mu.Unlock()
		if err != nil {
			h.failure, h.failedAt = err, now
			return nil, err
		}
		h.keys, h.issuer, h.cachedAt, h.lastFetch, h.failure = keys, issuer, now, now, nil
		return keys, nil
	})
	select {
	case r := <-ch:
		if r.Err != nil {
			return nil, r.Err
		}
		return r.Val.([]jwk), nil
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

// signingKey is get_signing_key: a miss refetches once, unless a fetch
// happened within the cooldown.
func (h *hydra) signingKey(ctx context.Context, now time.Time, keys []jwk, kid string, hasKid bool) (verifyKey, bool) {
	match := func(keys []jwk) verifyKey {
		for _, k := range keys {
			if hasKid && k.kid == kid {
				return k.key
			}
		}
		return nil
	}
	if key := match(keys); key != nil {
		return key, true
	}
	fresh, err := h.signingKeys(ctx, now, true)
	if err != nil {
		return nil, false
	}
	key := match(fresh)
	return key, key != nil
}

func (h *hydra) logUnavailable(err error) {
	h.logMu.Lock()
	defer h.logMu.Unlock()
	now := time.Now()
	if !h.lastUnavailLg.IsZero() && now.Sub(h.lastUnavailLg) < hydraUnavailableLogGap {
		return
	}
	h.lastUnavailLg = now
	h.log.Warn("Hydra's JWKS is unavailable; tokens are not checked as Hydra's (at most every 600s)", "error", err.Error())
}

func (h *hydra) refusal(detail string) *port.Error {
	return &port.Error{Status: http.StatusUnauthorized, Detail: detail, WWWAuthenticate: h.challenge}
}

// try is _try_hydra_token: (nil, nil) when the token is not Hydra's; an
// *port.Error refusing a token Hydra signed; any other error is internal.
func (h *hydra) try(ctx context.Context, token string, now time.Time) (*port.Principal, error) {
	header, _, headerErr := decodeComplete(token, decodeOptions{})
	if je, ok := asJWTError(headerErr); ok && je.decodeError() {
		h.log.Debug("Bearer token is not Hydra's", "error", je.msg)
		return nil, nil
	}
	keys, err := h.signingKeys(ctx, now, false)
	if err != nil {
		h.logUnavailable(err)
		return nil, nil
	}
	if headerErr != nil {
		return nil, headerErr
	}
	kid, hasKid := header["kid"].(string)
	key, found := h.signingKey(ctx, now, keys, kid, hasKid)
	if !found {
		h.log.Debug("Bearer token is not Hydra's: no signing key matches its kid")
		return nil, nil
	}

	if h.audience == "" {
		h.log.Warn("Hydra bearer token presented but AGENTAREA_AUTH_HYDRA_AUDIENCE is not configured; refusing the token. " +
			"Set AGENTAREA_AUTH_HYDRA_AUDIENCE to this API's resource identifier to enable MCP OAuth.")
		return nil, h.refusal("OAuth tokens are not accepted by this API")
	}
	audience := h.audience
	payload, err := decode(token, decodeOptions{
		verifySignature: true,
		key:             key,
		algorithms:      []string{"RS256"},
		audience:        &audience,
		now:             unixSeconds(now),
	})
	if err != nil {
		je, ok := asJWTError(err)
		if !ok || !je.invalidToken() {
			return nil, err
		}
		if je.class == clsExpired {
			h.log.Info("Hydra token refused: expired")
			return nil, h.refusal("Token has expired")
		}
		h.log.Warn("Hydra token refused", "error", je.msg)
		return nil, h.refusal(hydraRefusalDetail(je))
	}
	subject, _ := payload["sub"].(string)
	if subject == "" {
		h.log.Warn("Hydra token refused: no subject")
		return nil, h.refusal("OAuth token names no user")
	}
	if clientID, isStr := payload["client_id"].(string); isStr && clientID == subject {
		h.log.Warn("Hydra token refused: subject is its own client", "client_id", subject)
		return nil, h.refusal("OAuth token was issued to a client, not a signed-in user")
	}
	h.mu.Lock()
	issuer := h.issuer
	h.mu.Unlock()
	if iss, _ := payload["iss"].(string); iss != issuer {
		h.log.Warn("Hydra token refused: not issued by Hydra's issuer", "iss", payload["iss"], "issuer", issuer)
		return nil, h.refusal(detailHydraIssuer)
	}
	granted := grantedScopes(payload["scp"])
	p := &port.Principal{
		UserID:     subject,
		Credential: &port.Credential{Kind: port.KindOAuth, Surface: port.SurfaceAPI, Granted: granted},
	}
	switch {
	case slices.Contains(granted, port.OAuthScopeAPI):
		if cid, _ := payload["client_id"].(string); !slices.Contains(port.FirstPartyClientIDs(), cid) {
			h.log.Warn("Hydra token refused: api granted to a client that is not first-party", "client_id", payload["client_id"])
			return nil, h.refusal(detailHydraNoGrant)
		}
	case slices.Contains(granted, port.OAuthScopeMCP):
		ws, _ := payload["workspace_id"].(string)
		if ws == "" {
			h.log.Warn("Hydra token refused: mcp names no workspace", "client_id", payload["client_id"])
			return nil, h.refusal(detailHydraNoWorkspace)
		}
		p.BoundWorkspaceID = ws
	default:
		h.log.Info("Hydra token refused: grants neither mcp nor api", "client_id", payload["client_id"], "scp", payload["scp"])
		return nil, h.refusal(detailHydraNoGrant)
	}
	return p, nil
}

// grantedScopes is Hydra's scp claim: a list of strings, anything else none.
func grantedScopes(raw any) []string {
	list, _ := raw.([]any)
	out := make([]string, 0, len(list))
	for _, v := range list {
		if s, ok := v.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

func hydraRefusalDetail(je *jwtError) string {
	switch je.class { //nolint:exhaustive // every other PyJWT error is "Invalid OAuth token"
	case clsInvalidAudience:
		return "Token was not issued for this API"
	case clsInvalidSignature:
		return "Token signature is invalid"
	case clsImmature:
		return "Token is not valid yet"
	case clsMissingClaim:
		return "Token is missing a required claim"
	default:
		return "Invalid OAuth token"
	}
}

func unixSeconds(t time.Time) float64 { return float64(t.UnixNano()) / 1e9 }
