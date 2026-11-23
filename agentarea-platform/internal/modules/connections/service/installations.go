package service

import (
	"bytes"
	"context"
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"slices"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
)

// The auth config keys of a connection bound to one GitHub App installation.
const (
	cfgInstallationID      = "installation_id"
	cfgInstallationAccount = "installation_account"
	cfgInstallationRepos   = "installation_repositories"
)

const (
	githubTimeout = 15 * time.Second
	// installationTokenMargin is how long before its expiry a cached
	// installation token is replaced.
	installationTokenMargin = 5 * time.Minute
	// maxGitHubPages bounds a paginated listing (100 per page).
	maxGitHubPages = 50
	// maxBoundRepositories is what GitHub accepts in one token request.
	maxBoundRepositories = 500
)

// Installation is one installation of a platform GitHub App that the
// connection's user can access.
type Installation struct {
	ID                  int64
	Account             string
	AccountType         string
	RepositorySelection string
}

// InstallationRepository is one repository of an installation the user can access.
type InstallationRepository struct {
	Name     string
	FullName string
	Private  bool
}

// InstallationBinding is the installation a connection's calls are limited
// to; Repositories nil is every repository of the installation.
type InstallationBinding struct {
	InstallationID int64
	Account        string
	Repositories   []string
}

// InstallationBindingRequest is what a caller binds a connection to.
type InstallationBindingRequest struct {
	InstallationID int64
	Repositories   []string
}

// installationBindingOf reads the binding an auth config holds.
func installationBindingOf(cfg map[string]any) (InstallationBinding, bool) {
	id, ok := oaPyInt(cfg[cfgInstallationID])
	if !ok || id <= 0 {
		return InstallationBinding{}, false
	}
	b := InstallationBinding{InstallationID: id, Account: oaPyStr(cfg[cfgInstallationAccount])}
	if _, set := cfg[cfgInstallationRepos]; set {
		b.Repositories = domain.StringList(cfg[cfgInstallationRepos])
	}
	return b, true
}

// carryInstallationBinding keeps a connection on its installation when it
// signs in again through the same app; the next token checks the new
// sign-in still reaches it.
func carryInstallationBinding(cur *domain.AuthConfig, issuer string, cfg map[string]any) {
	if cur == nil || !domain.IsManaged(cur.Config) || oaPyStr(cur.Config["platform_oauth_issuer"]) != issuer {
		return
	}
	if _, ok := installationBindingOf(cur.Config); !ok {
		return
	}
	for _, k := range []string{cfgInstallationID, cfgInstallationAccount, cfgInstallationRepos} {
		if v, ok := cur.Config[k]; ok {
			cfg[k] = v
		}
	}
}

// installationTokens caches minted installation tokens per binding; each
// entry's lock makes concurrent calls wait for one mint.
type installationTokens struct {
	mu      sync.Mutex
	entries map[string]*installationToken
}

type installationToken struct {
	mu      sync.Mutex
	token   string
	expires time.Time
}

func (c *installationTokens) entry(key string) *installationToken {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.entries == nil {
		c.entries = map[string]*installationToken{}
	}
	e, ok := c.entries[key]
	if !ok {
		e = &installationToken{}
		c.entries[key] = e
	}
	return e
}

// installationToken is the access token of a bound connection: cached until
// shortly before it expires, minted again after a check that the
// connection's user still reaches the installation.
func (s *Service) installationToken(ctx context.Context, ws scope.Workspace, a domain.AuthConfig, creds map[string]any, app *OAuthApp, b InstallationBinding, force bool) (string, error) {
	key := a.ID + "|" + strconv.FormatInt(b.InstallationID, 10) + "|" + strings.Join(b.Repositories, ",")
	e := s.installTokens.entry(key)
	e.mu.Lock()
	defer e.mu.Unlock()
	if !force && e.token != "" && s.d.Now().Before(e.expires.Add(-installationTokenMargin)) {
		return e.token, nil
	}
	user, err := s.oauthToken(ctx, ws, a, creds, false)
	if err != nil {
		return "", err
	}
	if _, err := s.userInstallation(ctx, app, user, b.InstallationID); err != nil {
		var oe *OAuthError
		if errors.As(err, &oe) && oe.Status == http.StatusNotFound {
			return "", &domain.ReauthRequired{Msg: fmt.Sprintf("auth config %s is bound to GitHub App installation %d, which its user no longer reaches; bind it again", a.ID, b.InstallationID)}
		}
		return "", err
	}
	token, expires, err := s.mintInstallationToken(ctx, app, b)
	if err != nil {
		return "", err
	}
	e.token, e.expires = token, expires
	s.d.Log.InfoContext(ctx, "Minted GitHub App installation token", "auth_config_id", a.ID, "installation_id", b.InstallationID)
	return token, nil
}

// appJWT is the GitHub App's own credential: RS256, issued by the app id,
// valid for nine minutes from a minute ago (clock drift).
func appJWT(app *OAuthApp, now time.Time) (string, error) {
	iss, err := app.AppID.Int64()
	if err != nil {
		return "", fmt.Errorf("app_id of %s: %w", app.Issuer, err)
	}
	enc := base64.RawURLEncoding
	header := enc.EncodeToString([]byte(`{"alg":"RS256","typ":"JWT"}`))
	claims, err := json.Marshal(map[string]int64{"iat": now.Add(-time.Minute).Unix(), "exp": now.Add(9 * time.Minute).Unix(), "iss": iss})
	if err != nil {
		return "", err
	}
	signed := header + "." + enc.EncodeToString(claims)
	sum := sha256.Sum256([]byte(signed))
	sig, err := rsa.SignPKCS1v15(rand.Reader, app.InstallationKey, crypto.SHA256, sum[:])
	if err != nil {
		return "", err
	}
	return signed + "." + enc.EncodeToString(sig), nil
}

// mintInstallationToken asks GitHub for an installation access token,
// limited to the binding's repositories when it names any.
func (s *Service) mintInstallationToken(ctx context.Context, app *OAuthApp, b InstallationBinding) (string, time.Time, error) {
	jwt, err := appJWT(app, s.d.Now())
	if err != nil {
		return "", time.Time{}, err
	}
	var body io.Reader
	if len(b.Repositories) > 0 {
		raw, err := json.Marshal(map[string][]string{"repositories": b.Repositories})
		if err != nil {
			return "", time.Time{}, err
		}
		body = bytes.NewReader(raw)
	}
	var out struct {
		Token     string `json:"token"`
		ExpiresAt string `json:"expires_at"`
	}
	path := "/app/installations/" + strconv.FormatInt(b.InstallationID, 10) + "/access_tokens"
	status, err := s.githubCall(ctx, app, http.MethodPost, path, jwt, body, &out)
	if err != nil {
		return "", time.Time{}, err
	}
	if status != http.StatusCreated && status != http.StatusOK {
		return "", time.Time{}, &domain.ReauthRequired{Msg: fmt.Sprintf("GitHub refused an installation token for installation %d (%d); bind the connection again", b.InstallationID, status)}
	}
	expires, err := time.Parse(time.RFC3339, out.ExpiresAt)
	if out.Token == "" || err != nil {
		return "", time.Time{}, fmt.Errorf("GitHub answered installation %d with no token or expiry", b.InstallationID)
	}
	return out.Token, expires, nil
}

// githubCall sends one request to the app's API and decodes a 2xx answer into out.
func (s *Service) githubCall(ctx context.Context, app *OAuthApp, method, path, bearer string, body io.Reader, out any) (int, error) {
	req, err := http.NewRequestWithContext(ctx, method, app.APIURL+path, body)
	if err != nil {
		return 0, netguard.SafeURLError(err)
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("X-GitHub-Api-Version", "2022-11-28")
	req.Header.Set("Authorization", "Bearer "+bearer)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := s.httpClient(netguard.Vendor, githubTimeout, false).Do(req)
	if err != nil {
		return 0, netguard.SafeURLError(err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, maxOAuthBody))
	if err != nil {
		return resp.StatusCode, err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return resp.StatusCode, nil
	}
	if err := json.Unmarshal(raw, out); err != nil {
		return resp.StatusCode, fmt.Errorf("GitHub answered %s with no JSON object: %w", path, err)
	}
	return resp.StatusCode, nil
}

// githubUserGet is githubCall with the connection's user token: a refused
// token is a sign-in to repeat, any other failure GitHub's.
func (s *Service) githubUserGet(ctx context.Context, app *OAuthApp, token, path string, out any) (int, error) {
	status, err := s.githubCall(ctx, app, http.MethodGet, path, token, nil, out)
	if err != nil {
		return status, err
	}
	switch {
	case status == http.StatusUnauthorized:
		return status, &domain.ReauthRequired{Msg: "GitHub refused the connection's sign-in; reconnect it"}
	case status == http.StatusNotFound || status == http.StatusForbidden:
		return status, nil
	case status < 200 || status >= 300:
		return status, oaHttpErr(http.StatusBadGateway, fmt.Sprintf("GitHub answered %d", status))
	}
	return status, nil
}

// userInstallations lists the app's installations the user token reaches.
func (s *Service) userInstallations(ctx context.Context, app *OAuthApp, token string) ([]Installation, error) {
	var out []Installation
	for page := 1; page <= maxGitHubPages; page++ {
		var body struct {
			Installations []struct {
				ID      int64       `json:"id"`
				AppID   json.Number `json:"app_id"`
				Account struct {
					Login string `json:"login"`
					Type  string `json:"type"`
				} `json:"account"`
				RepositorySelection string `json:"repository_selection"`
			} `json:"installations"`
		}
		status, err := s.githubUserGet(ctx, app, token, "/user/installations?per_page=100&page="+strconv.Itoa(page), &body)
		if err != nil {
			return nil, err
		}
		if status != http.StatusOK {
			return nil, oaHttpErr(http.StatusBadGateway, fmt.Sprintf("GitHub answered %d", status))
		}
		for _, i := range body.Installations {
			if i.AppID.String() == app.AppID.String() {
				out = append(out, Installation{ID: i.ID, Account: i.Account.Login, AccountType: i.Account.Type, RepositorySelection: i.RepositorySelection})
			}
		}
		if len(body.Installations) < 100 {
			break
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out, nil
}

// userInstallation is the app's installation id when the user token reaches it; 404 otherwise.
func (s *Service) userInstallation(ctx context.Context, app *OAuthApp, token string, id int64) (Installation, error) {
	list, err := s.userInstallations(ctx, app, token)
	if err != nil {
		return Installation{}, err
	}
	for _, i := range list {
		if i.ID == id {
			return i, nil
		}
	}
	return Installation{}, oaHttpErr(http.StatusNotFound, fmt.Sprintf("Installation %d is not one this connection's GitHub user can access through the app.", id))
}

// installationRepositories lists the repositories of installation id the user token reaches.
func (s *Service) installationRepositories(ctx context.Context, app *OAuthApp, token string, id int64) ([]InstallationRepository, error) {
	var out []InstallationRepository
	for page := 1; page <= maxGitHubPages; page++ {
		var body struct {
			TotalCount   int `json:"total_count"`
			Repositories []struct {
				Name     string `json:"name"`
				FullName string `json:"full_name"`
				Private  bool   `json:"private"`
			} `json:"repositories"`
		}
		path := "/user/installations/" + strconv.FormatInt(id, 10) + "/repositories?per_page=100&page=" + strconv.Itoa(page)
		status, err := s.githubUserGet(ctx, app, token, path, &body)
		if err != nil {
			return nil, err
		}
		if status != http.StatusOK {
			return nil, oaHttpErr(http.StatusNotFound, fmt.Sprintf("Installation %d is not one this connection's GitHub user can access through the app.", id))
		}
		for _, r := range body.Repositories {
			out = append(out, InstallationRepository{Name: r.Name, FullName: r.FullName, Private: r.Private})
		}
		if len(body.Repositories) == 0 || len(out) >= body.TotalCount {
			break
		}
	}
	return out, nil
}

// installationTarget is the signed-in connection a binding call acts on,
// for whoever may sign it in again, and the app it signed in through.
func (s *Service) installationTarget(ctx context.Context, c authn.Caller, ref OAuthTarget) (domain.AuthConfig, *OAuthApp, error) {
	if ref.InstanceID == nil && ref.OpenAPIConnectionID == nil {
		return domain.AuthConfig{}, nil, oaHttpErr(http.StatusUnprocessableEntity, "Pass exactly one of instance_id or openapi_connection_id.")
	}
	t, err := s.loadTarget(ctx, c, ref)
	if err != nil {
		return domain.AuthConfig{}, nil, err
	}
	if err := t.ensure(ctx); err != nil {
		return domain.AuthConfig{}, nil, err
	}
	if t.current == nil {
		return domain.AuthConfig{}, nil, oaHttpErr(http.StatusConflict, "Sign in to this connection first.")
	}
	app, err := s.platformApp(*t.current)
	if err != nil || !app.MintsInstallationTokens() {
		return domain.AuthConfig{}, nil, oaHttpErr(http.StatusConflict, "This connection did not sign in through an app whose installations it can be bound to.")
	}
	return *t.current, app, nil
}

// connectionUserToken is the user token the connection holds, renewed when due.
func (s *Service) connectionUserToken(ctx context.Context, ws scope.Workspace, a domain.AuthConfig) (string, error) {
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return "", err
	}
	creds, err := oaLoadCredentials(ctx, s.d.Secrets.Manager(sess, a.CreatedBy), a)
	release()
	if err != nil {
		return "", err
	}
	token, err := s.oauthToken(ctx, ws, a, creds, false)
	var ra *domain.ReauthRequired
	if errors.As(err, &ra) {
		return "", oaHttpErr(http.StatusConflict, "The connection's sign-in has expired. Reconnect it.")
	}
	return token, err
}

// OAuthInstallations lists the installations of the connection's app its
// GitHub user can access.
func (s *Service) OAuthInstallations(ctx context.Context, c authn.Caller, ref OAuthTarget) ([]Installation, error) {
	a, app, err := s.installationTarget(ctx, c, ref)
	if err != nil {
		return nil, err
	}
	token, err := s.connectionUserToken(ctx, c.Workspace, a)
	if err != nil {
		return nil, err
	}
	return reauthAsConflict(s.userInstallations(ctx, app, token))
}

// OAuthInstallationRepositories lists the repositories of one of those
// installations the user can access.
func (s *Service) OAuthInstallationRepositories(ctx context.Context, c authn.Caller, ref OAuthTarget, id int64) ([]InstallationRepository, error) {
	a, app, err := s.installationTarget(ctx, c, ref)
	if err != nil {
		return nil, err
	}
	token, err := s.connectionUserToken(ctx, c.Workspace, a)
	if err != nil {
		return nil, err
	}
	if _, err := reauthAsConflict(s.userInstallation(ctx, app, token, id)); err != nil {
		return nil, err
	}
	return reauthAsConflict(s.installationRepositories(ctx, app, token, id))
}

// BindOAuthInstallation limits the connection's calls to one installation
// (and, when named, some of its repositories) its user can access; nil
// returns it to the user token.
func (s *Service) BindOAuthInstallation(ctx context.Context, c authn.Caller, ref OAuthTarget, req *InstallationBindingRequest) (*InstallationBinding, error) {
	a, app, err := s.installationTarget(ctx, c, ref)
	if err != nil {
		return nil, err
	}
	cfg := make(map[string]any, len(a.Config)+3)
	for k, v := range a.Config {
		cfg[k] = v
	}
	delete(cfg, cfgInstallationID)
	delete(cfg, cfgInstallationAccount)
	delete(cfg, cfgInstallationRepos)
	var out *InstallationBinding
	if req != nil {
		b, err := s.checkBinding(ctx, c, a, app, *req)
		if err != nil {
			return nil, err
		}
		cfg[cfgInstallationID] = b.InstallationID
		cfg[cfgInstallationAccount] = b.Account
		if b.Repositories != nil {
			repos := make([]any, len(b.Repositories))
			for i, r := range b.Repositories {
				repos[i] = r
			}
			cfg[cfgInstallationRepos] = repos
		}
		out = &b
	}
	id, err := uuid.Parse(a.ID)
	if err != nil {
		return nil, err
	}
	err = s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		return s.d.Auth.Update(ctx, sess, id, nil, nil, cfg, s.d.Now())
	})
	if err != nil {
		return nil, err
	}
	s.d.Log.InfoContext(ctx, "OAuth connection installation binding changed", "auth_config_id", a.ID, "bound", out != nil)
	return out, nil
}

// checkBinding admits only an installation the connection's user can access
// and repositories of it they can access.
func (s *Service) checkBinding(ctx context.Context, c authn.Caller, a domain.AuthConfig, app *OAuthApp, req InstallationBindingRequest) (InstallationBinding, error) {
	token, err := s.connectionUserToken(ctx, c.Workspace, a)
	if err != nil {
		return InstallationBinding{}, err
	}
	inst, err := reauthAsConflict(s.userInstallation(ctx, app, token, req.InstallationID))
	if err != nil {
		var oe *OAuthError
		if errors.As(err, &oe) && oe.Status == http.StatusNotFound {
			oe.Status = http.StatusUnprocessableEntity
		}
		return InstallationBinding{}, err
	}
	b := InstallationBinding{InstallationID: inst.ID, Account: inst.Account}
	if len(req.Repositories) == 0 {
		return b, nil
	}
	var names []string
	for _, r := range req.Repositories {
		if !slices.Contains(names, r) {
			names = append(names, r)
		}
	}
	if len(names) > maxBoundRepositories {
		return b, oaHttpErr(http.StatusUnprocessableEntity, fmt.Sprintf("A connection can be limited to at most %d repositories.", maxBoundRepositories))
	}
	repos, err := reauthAsConflict(s.installationRepositories(ctx, app, token, inst.ID))
	if err != nil {
		return b, err
	}
	for _, n := range names {
		if !slices.ContainsFunc(repos, func(r InstallationRepository) bool { return r.Name == n }) {
			return b, oaHttpErr(http.StatusUnprocessableEntity, fmt.Sprintf("Repository %q is not one of %s's this connection's GitHub user can access.", n, inst.Account))
		}
	}
	b.Repositories = names
	return b, nil
}

// installationBindingView is the binding preflight reports, and whether the
// connection can be bound at all.
func (s *Service) installationBindingView(a *domain.AuthConfig) (bool, *InstallationBinding) {
	if a == nil {
		return false, nil
	}
	app, err := s.platformApp(*a)
	if err != nil || !app.MintsInstallationTokens() {
		return false, nil
	}
	b, ok := installationBindingOf(a.Config)
	if !ok {
		return true, nil
	}
	return true, &b
}

func reauthAsConflict[T any](v T, err error) (T, error) {
	var ra *domain.ReauthRequired
	if errors.As(err, &ra) {
		return v, oaHttpErr(http.StatusConflict, "The connection's sign-in was refused by GitHub. Reconnect it.")
	}
	return v, err
}
