package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"slices"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
)

// FirstPartyClients are the OAuth clients the platform registers itself;
// only they are granted api (ADR-0058).
func FirstPartyClients() []FirstPartyClient {
	return []FirstPartyClient{
		{ID: "agentarea-cli", Name: "AgentArea CLI", RedirectURIs: []string{"http://127.0.0.1/callback"}},
		{ID: "agentarea-desktop", Name: "AgentArea Desktop", RedirectURIs: []string{"http://127.0.0.1:14321/callback"}},
	}
}

// FirstPartyClient is a public client with loopback redirects; Hydra matches
// a loopback redirect on any port (RFC 8252).
type FirstPartyClient struct {
	ID           string
	Name         string
	RedirectURIs []string
}

func isFirstParty(clientID string) bool {
	return slices.Contains(authn.FirstPartyClientIDs(), clientID)
}

// protocolScopes grant nothing on their own; a consent passes on those the
// client asked for.
func protocolScopes() []string { return []string{"openid", "offline_access", "offline"} }

// ConsentGrant is what a consent gives client: api to a first-party client,
// mcp to any other, plus the protocol scopes it requested. What a client
// asks of our own scopes is never read.
func ConsentGrant(clientID string, requested []string) (access string, scopes []string) {
	access = authn.OAuthScopeMCP
	if isFirstParty(clientID) {
		access = authn.OAuthScopeAPI
	}
	scopes = []string{access}
	for _, sc := range requested {
		if slices.Contains(protocolScopes(), sc) && !slices.Contains(scopes, sc) {
			scopes = append(scopes, sc)
		}
	}
	return access, scopes
}

// Consent refusals the handlers map to statuses.
var (
	ErrConsentNotFound       = errors.New("consent request not found or expired")
	ErrConsentNotYours       = errors.New("consent request belongs to another user")
	ErrConsentNeedsWorkspace = errors.New("this client is granted the workspaces picked; pick at least one")
)

// ConsentClient is the client a consent is asked for, as Hydra holds it.
type ConsentClient struct {
	ID           string   `json:"client_id"`
	Name         string   `json:"client_name"`
	URI          string   `json:"client_uri"`
	LogoURI      string   `json:"logo_uri"`
	RedirectURIs []string `json:"redirect_uris"`
	Scope        string   `json:"scope"`
	Audience     []string `json:"audience"`
}

type consentRequest struct {
	Subject           string        `json:"subject"`
	RequestURL        string        `json:"request_url"`
	RequestedScope    []string      `json:"requested_scope"`
	RequestedAudience []string      `json:"requested_access_token_audience"`
	Client            ConsentClient `json:"client"`
}

// Consent is what the consent screen shows: the client, where the code goes,
// and what accepting grants it.
type Consent struct {
	Client      ConsentClient
	RedirectURI string
	FirstParty  bool
	Access      string
	Scopes      []string
}

// Consent loads the consent request challenge names for userID.
func (s *Service) Consent(ctx context.Context, userID, challenge string) (Consent, error) {
	req, err := s.consentRequest(ctx, userID, challenge)
	if err != nil {
		return Consent{}, err
	}
	access, scopes := ConsentGrant(req.Client.ID, req.RequestedScope)
	c := req.Client
	c.Scope, c.Audience = "", nil
	return Consent{Client: c, RedirectURI: req.redirectURI(), FirstParty: isFirstParty(req.Client.ID), Access: access, Scopes: scopes}, nil
}

// redirectURI is where accepting sends the code: the authorize request's
// redirect_uri, or the client's only registered one; "" when neither is known.
func (r consentRequest) redirectURI() string {
	if u, err := url.Parse(r.RequestURL); err == nil && r.RequestURL != "" {
		if v := u.Query().Get("redirect_uri"); v != "" {
			return v
		}
	}
	if len(r.Client.RedirectURIs) == 1 {
		return r.Client.RedirectURIs[0]
	}
	return ""
}

// AcceptConsent grants the consent challenge names; workspaceIDs are the
// workspaces an mcp grant is bound to, already admitted for userID. The
// client's allowed scopes are widened first: Hydra issues a scope the client
// is not allowed, then refuses the client's refresh. Returns Hydra's redirect.
func (s *Service) AcceptConsent(ctx context.Context, userID, challenge string, workspaceIDs []string) (string, error) {
	req, err := s.consentRequest(ctx, userID, challenge)
	if err != nil {
		return "", err
	}
	access, scopes := ConsentGrant(req.Client.ID, req.RequestedScope)
	body := map[string]any{
		"grant_scope":                 scopes,
		"grant_access_token_audience": grantedAudience(req.RequestedAudience, req.Client.Audience),
		"remember":                    false,
	}
	if access == authn.OAuthScopeMCP {
		if len(workspaceIDs) == 0 {
			return "", ErrConsentNeedsWorkspace
		}
		body["session"] = map[string]any{"access_token": map[string]any{"workspace_ids": workspaceIDs}}
	}
	if err := s.allowClientScopes(ctx, req.Client, scopes); err != nil {
		return "", err
	}
	return s.decideConsent(ctx, challenge, "accept", body)
}

// RejectConsent denies the consent challenge names.
func (s *Service) RejectConsent(ctx context.Context, userID, challenge string) (string, error) {
	if _, err := s.consentRequest(ctx, userID, challenge); err != nil {
		return "", err
	}
	return s.decideConsent(ctx, challenge, "reject", map[string]any{
		"error": "access_denied", "error_description": "The user denied the request",
	})
}

func grantedAudience(requested, client []string) []string {
	if len(requested) > 0 {
		return requested
	}
	if client == nil {
		return []string{}
	}
	return client
}

func (s *Service) consentURL(suffix, challenge string) string {
	return strings.TrimRight(s.d.Config.HydraAdminURL, "/") + "/admin/oauth2/auth/requests/consent" + suffix +
		"?consent_challenge=" + url.QueryEscape(challenge)
}

func (s *Service) consentRequest(ctx context.Context, userID, challenge string) (consentRequest, error) {
	var req consentRequest
	if challenge == "" {
		return req, ErrConsentNotFound
	}
	status, raw, err := s.hydraAdmin(ctx, http.MethodGet, s.consentURL("", challenge), nil)
	if err != nil {
		return req, err
	}
	if status == http.StatusNotFound || status == http.StatusGone {
		return req, ErrConsentNotFound
	}
	if status != http.StatusOK {
		return req, fmt.Errorf("hydra consent request: status %d", status)
	}
	if err := json.Unmarshal(raw, &req); err != nil {
		return req, fmt.Errorf("hydra consent request: %w", err)
	}
	if userID == "" || req.Subject != userID {
		return req, ErrConsentNotYours
	}
	return req, nil
}

func (s *Service) decideConsent(ctx context.Context, challenge, action string, body map[string]any) (string, error) {
	status, raw, err := s.hydraAdmin(ctx, http.MethodPut, s.consentURL("/"+action, challenge), body)
	if err != nil {
		return "", err
	}
	if status == http.StatusNotFound || status == http.StatusGone || status == http.StatusConflict {
		return "", ErrConsentNotFound
	}
	if status != http.StatusOK {
		return "", fmt.Errorf("hydra consent %s: status %d", action, status)
	}
	var out struct {
		RedirectTo string `json:"redirect_to"`
	}
	if err := json.Unmarshal(raw, &out); err != nil || out.RedirectTo == "" {
		return "", fmt.Errorf("hydra consent %s returned no redirect", action)
	}
	return out.RedirectTo, nil
}

// allowClientScopes adds the scopes the client is not yet allowed to its
// registration, keeping the rest.
func (s *Service) allowClientScopes(ctx context.Context, client ConsentClient, scopes []string) error {
	allowed := strings.Fields(client.Scope)
	missing := false
	for _, sc := range scopes {
		if !slices.Contains(allowed, sc) {
			allowed, missing = append(allowed, sc), true
		}
	}
	if !missing {
		return nil
	}
	target := strings.TrimRight(s.d.Config.HydraAdminURL, "/") + "/admin/clients/" + url.PathEscape(client.ID)
	patch := []map[string]any{{"op": "replace", "path": "/scope", "value": strings.Join(allowed, " ")}}
	status, _, err := s.hydraAdmin(ctx, http.MethodPatch, target, patch)
	if err != nil {
		return err
	}
	if status != http.StatusOK {
		return fmt.Errorf("hydra client %q scope update: status %d", client.ID, status)
	}
	return nil
}

func (s *Service) hydraAdmin(ctx context.Context, method, target string, body any) (int, []byte, error) {
	var rd io.Reader
	if body != nil {
		raw, err := json.Marshal(body)
		if err != nil {
			return 0, nil, err
		}
		rd = strings.NewReader(string(raw))
	}
	req, err := http.NewRequestWithContext(ctx, method, target, rd)
	if err != nil {
		return 0, nil, err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := s.internalClient(15 * time.Second).Do(req)
	if err != nil {
		return 0, nil, err
	}
	defer func() { _ = resp.Body.Close() }()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, maxOAuthBody))
	return resp.StatusCode, raw, err
}

// EnsureFirstPartyClients creates each first-party client in Hydra, or
// rewrites it to its definition; the migrate role runs it on every deploy.
func EnsureFirstPartyClients(ctx context.Context, hc *http.Client, adminURL, audience string) error {
	base := strings.TrimRight(adminURL, "/") + "/admin/clients"
	for _, c := range FirstPartyClients() {
		body, err := json.Marshal(map[string]any{
			"client_id": c.ID, "client_name": c.Name, "redirect_uris": c.RedirectURIs,
			"grant_types": []string{"authorization_code", "refresh_token"}, "response_types": []string{"code"},
			"scope":                      strings.Join(append([]string{authn.OAuthScopeAPI}, protocolScopes()...), " "),
			"token_endpoint_auth_method": "none", "audience": []string{audience}, "skip_consent": false,
		})
		if err != nil {
			return err
		}
		status, err := hydraClientWrite(ctx, hc, http.MethodPut, base+"/"+url.PathEscape(c.ID), body)
		if err == nil && status == http.StatusNotFound {
			status, err = hydraClientWrite(ctx, hc, http.MethodPost, base, body)
		}
		if err != nil {
			return fmt.Errorf("first-party client %s: %w", c.ID, err)
		}
		if status != http.StatusOK && status != http.StatusCreated {
			return fmt.Errorf("first-party client %s: hydra answered %d", c.ID, status)
		}
	}
	return nil
}

func hydraClientWrite(ctx context.Context, hc *http.Client, method, target string, body []byte) (int, error) {
	req, err := http.NewRequestWithContext(ctx, method, target, strings.NewReader(string(body)))
	if err != nil {
		return 0, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := hc.Do(req)
	if err != nil {
		return 0, err
	}
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, maxOAuthBody))
	_ = resp.Body.Close()
	return resp.StatusCode, nil
}
