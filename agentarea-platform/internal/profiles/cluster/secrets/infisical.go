package secrets

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	kernel "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
)

// InfisicalClient is the shared connection to Infisical: universal-auth
// login, with the access token cached until shortly before it expires.
type InfisicalClient struct {
	host         string
	clientID     string
	clientSecret string
	project      string
	env          string
	http         *http.Client
	now          func() time.Time

	mu     sync.Mutex
	token  string
	expiry time.Time
}

// NewInfisicalClient builds the client from validated config; no request is made.
func NewInfisicalClient(cfg kernel.Config, hc *http.Client) *InfisicalClient {
	if hc == nil {
		hc = &http.Client{Timeout: 30 * time.Second}
	}
	return &InfisicalClient{
		host: strings.TrimRight(cfg.Endpoint, "/"), clientID: cfg.ClientID, clientSecret: cfg.ClientSecret,
		project: cfg.ProjectID, env: cfg.Env, http: hc, now: time.Now,
	}
}

func (c *InfisicalClient) accessToken(ctx context.Context) (string, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.token != "" && c.now().Before(c.expiry) {
		return c.token, nil
	}
	body, _ := json.Marshal(map[string]string{"clientId": c.clientID, "clientSecret": c.clientSecret})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.host+"/api/v1/auth/universal-auth/login", bytes.NewReader(body))
	if err != nil {
		return "", errors.New("infisical: bad endpoint")
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.http.Do(req)
	if err != nil {
		return "", fmt.Errorf("infisical login failed (%T)", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("infisical login rejected: status %d", resp.StatusCode)
	}
	var out struct {
		AccessToken string `json:"accessToken"`
		ExpiresIn   int    `json:"expiresIn"`
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&out); err != nil || out.AccessToken == "" {
		return "", errors.New("infisical login returned no token")
	}
	c.token = out.AccessToken
	ttl := time.Duration(out.ExpiresIn) * time.Second
	c.expiry = c.now().Add(ttl - ttl/10)
	return c.token, nil
}

// errInfisicalNotFound is a 404: the one answer that means the secret is absent.
var errInfisicalNotFound = errors.New("infisical: secret not found")

func (c *InfisicalClient) do(ctx context.Context, method, name, path string, payload map[string]any) (map[string]any, error) {
	token, err := c.accessToken(ctx)
	if err != nil {
		return nil, err
	}
	endpoint := c.host + "/api/v3/secrets/raw/" + url.PathEscape(name)
	base := map[string]any{"workspaceId": c.project, "projectId": c.project, "environment": c.env, "secretPath": path, "type": "shared"}
	var body io.Reader
	if method == http.MethodGet {
		q := url.Values{}
		for _, k := range []string{"workspaceId", "projectId", "environment", "secretPath", "type"} {
			q.Set(k, base[k].(string))
		}
		q.Set("viewSecretValue", "true")
		endpoint += "?" + q.Encode()
	} else {
		for k, v := range payload {
			base[k] = v
		}
		raw, _ := json.Marshal(base)
		body = bytes.NewReader(raw)
	}
	req, err := http.NewRequestWithContext(ctx, method, endpoint, body)
	if err != nil {
		return nil, errors.New("infisical: bad request")
	}
	req.Header.Set("Authorization", "Bearer "+token)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("infisical request failed (%T)", err)
	}
	defer func() { _ = resp.Body.Close() }()
	switch {
	case resp.StatusCode == http.StatusNotFound:
		return nil, errInfisicalNotFound
	case resp.StatusCode < 200 || resp.StatusCode > 299:
		return nil, fmt.Errorf("infisical request rejected: status %d", resp.StatusCode)
	}
	var out map[string]any
	if err := json.NewDecoder(io.LimitReader(resp.Body, 4<<20)).Decode(&out); err != nil {
		return nil, errors.New("infisical returned an unreadable body")
	}
	return out, nil
}

// Infisical is the Infisical backend for one workspace
// (infisical_secret_manager.py). Every workspace gets its own secret path:
// without one, two workspaces using a name would read and overwrite each
// other's value.
type Infisical struct {
	c           *InfisicalClient
	workspaceID string
}

// ForWorkspace is the backend bound to a workspace.
func (c *InfisicalClient) ForWorkspace(workspaceID string) *Infisical {
	return &Infisical{c: c, workspaceID: workspaceID}
}

func (i *Infisical) path() string { return "/workspaces/" + i.workspaceID }

// ExternalRef is where the catalog row records the value lives.
func (i *Infisical) ExternalRef(name string) (string, bool) {
	return fmt.Sprintf("infisical://%s/%s%s/%s", i.c.project, i.c.env, i.path(), name), true
}

// Get returns ErrNotFound only for a genuine absence (404); an unreachable
// host, a rejected identity or an expired token propagate, because a caller
// told "no such secret" goes looking in the wrong place.
func (i *Infisical) Get(ctx context.Context, name string) (string, error) {
	out, err := i.c.do(ctx, http.MethodGet, name, i.path(), nil)
	if errors.Is(err, errInfisicalNotFound) {
		return "", kernel.ErrNotFound
	}
	if err != nil {
		return "", err
	}
	secret, _ := out["secret"].(map[string]any)
	value, ok := secret["secretValue"].(string)
	if !ok {
		return "", errors.New("infisical returned a secret without a value")
	}
	return value, nil
}

// Has reads the value: Infisical has no cheaper existence check here.
func (i *Infisical) Has(ctx context.Context, name string) (bool, error) {
	_, err := i.Get(ctx, name)
	if errors.Is(err, kernel.ErrNotFound) {
		return false, nil
	}
	return err == nil, err
}

// Set creates the secret, or updates it when present.
func (i *Infisical) Set(ctx context.Context, name, value string) error {
	exists, err := i.Has(ctx, name)
	if err != nil {
		return err
	}
	method := http.MethodPost
	if exists {
		method = http.MethodPatch
	}
	_, err = i.c.do(ctx, method, name, i.path(), map[string]any{"secretValue": value})
	return err
}

// Delete reports false when there was nothing to remove.
func (i *Infisical) Delete(ctx context.Context, name string) (bool, error) {
	exists, err := i.Has(ctx, name)
	if err != nil || !exists {
		return false, err
	}
	if _, err := i.c.do(ctx, http.MethodDelete, name, i.path(), nil); err != nil {
		return false, err
	}
	return true, nil
}

// infisicalUserSecrets reads Infisical only behind a user-owned catalog row:
// Infisical itself does not know who owns a name.
type infisicalUserSecrets struct {
	s   db.Session
	inf *Infisical
}

func (u infisicalUserSecrets) GetUserOwned(ctx context.Context, name string) (string, error) {
	var id string
	found, err := one(ctx, u.s.Q(),
		`SELECT id::text FROM encrypted_secrets WHERE workspace_id = $1 AND secret_name = $2 AND owner_type IS NULL`,
		[]any{u.s.Workspace().ID(), name}, &id)
	if err != nil {
		return "", fmt.Errorf("secret catalog lookup failed (%T)", err)
	}
	if !found {
		return "", kernel.ErrNotFound
	}
	return u.inf.Get(ctx, name)
}
