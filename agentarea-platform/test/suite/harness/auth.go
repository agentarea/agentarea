//go:build suite

package harness

import (
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sync"
	"testing"
	"time"
)

// User is a Kratos identity signed in through the password API flow, the way
// test/fuzz/harness.py mints its users. Its bearer is
// the agentarea_jwt the Kratos tokenizer issues (30-minute TTL), re-issued
// from the session before it lapses.
type User struct {
	ID           string
	Email        string
	SessionToken string

	mu       sync.Mutex
	jwt      string
	issuedAt time.Time
}

const (
	userPassword  = "Str0ng-Test-PW-xyz!"
	jwtRefreshAge = 15 * time.Minute
)

//nolint:gochecknoglobals // identities minted by this process, deleted by Main
var (
	kratosHTTP = &http.Client{Timeout: 30 * time.Second}

	mintedMu sync.Mutex
	minted   []string
)

// NewUser mints a fresh identity. The run deletes it at exit (Main).
func NewUser(t testing.TB, label string) *User {
	t.Helper()
	env := Current(t)
	email := fmt.Sprintf("suite-%s-%s@test.local", label, randomHex(4))

	var identity struct {
		ID string `json:"id"`
	}
	kratosJSON(t, http.MethodPost, env.KratosAdmin+"/admin/identities", nil, map[string]any{
		"schema_id":   "default",
		"traits":      map[string]any{"email": email},
		"credentials": map[string]any{"password": map[string]any{"config": map[string]any{"password": userPassword}}},
		"verifiable_addresses": []any{map[string]any{
			"value": email, "verified": true, "via": "email", "status": "completed",
		}},
	}, http.StatusCreated, &identity)
	mintedMu.Lock()
	minted = append(minted, identity.ID)
	mintedMu.Unlock()

	var flow struct {
		ID string `json:"id"`
	}
	kratosJSON(t, http.MethodGet, env.KratosPublic+"/self-service/login/api", nil, nil, http.StatusOK, &flow)
	var login struct {
		SessionToken string `json:"session_token"`
	}
	kratosJSON(t, http.MethodPost, env.KratosPublic+"/self-service/login?flow="+url.QueryEscape(flow.ID), nil,
		map[string]any{"method": "password", "identifier": email, "password": userPassword},
		http.StatusOK, &login)

	u := &User{ID: identity.ID, Email: email, SessionToken: login.SessionToken}
	u.refresh(t)
	return u
}

// JWT returns a bearer that is valid for at least another quarter hour.
func (u *User) JWT(t testing.TB) string {
	t.Helper()
	u.mu.Lock()
	stale := time.Since(u.issuedAt) > jwtRefreshAge
	u.mu.Unlock()
	if stale {
		u.refresh(t)
	}
	u.mu.Lock()
	defer u.mu.Unlock()
	return u.jwt
}

func (u *User) refresh(t testing.TB) {
	t.Helper()
	var whoami struct {
		Tokenized string `json:"tokenized"`
	}
	kratosJSON(t, http.MethodGet, Current(t).KratosPublic+"/sessions/whoami?tokenize_as=agentarea_jwt",
		http.Header{"X-Session-Token": {u.SessionToken}}, nil, http.StatusOK, &whoami)
	if whoami.Tokenized == "" {
		t.Fatal("kratos whoami returned no agentarea_jwt; is the tokenizer template configured?")
	}
	u.mu.Lock()
	u.jwt, u.issuedAt = whoami.Tokenized, time.Now()
	u.mu.Unlock()
}

// Client is a client authenticated as u.
func (u *User) Client(t testing.TB, name string) *Client {
	return newClient(name, Current(t).BaseURL, u.JWT)
}

func kratosJSON(t testing.TB, method, target string, header http.Header, body any, want int, out any) {
	t.Helper()
	var rd io.Reader
	if body != nil {
		raw, err := json.Marshal(body)
		if err != nil {
			t.Fatal(err)
		}
		rd = bytes.NewReader(raw)
	}
	req, err := http.NewRequest(method, target, rd)
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Accept", "application/json")
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	for k, vs := range header {
		req.Header[k] = vs
	}
	resp, err := kratosHTTP.Do(req)
	if err != nil {
		t.Fatalf("kratos %s %s: %v", method, target, err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != want {
		t.Fatalf("kratos %s %s: status %d, want %d: %s", method, target, resp.StatusCode, want, truncate(raw, 1000))
	}
	if out != nil {
		if err := json.Unmarshal(raw, out); err != nil {
			t.Fatalf("kratos %s %s: %v", method, target, err)
		}
	}
}

func deleteIdentities() {
	env, err := loadEnv()
	if err != nil {
		return
	}
	mintedMu.Lock()
	ids := minted
	minted = nil
	mintedMu.Unlock()
	for _, id := range ids {
		req, err := http.NewRequest(http.MethodDelete, env.KratosAdmin+"/admin/identities/"+id, nil)
		if err != nil {
			continue
		}
		if resp, err := kratosHTTP.Do(req); err == nil {
			_ = resp.Body.Close()
		}
	}
}

func randomHex(n int) string {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	return hex.EncodeToString(b)
}

// Principals are the three people every suite acts as, minted once per run.
type Principals struct {
	Owner, Member, Outsider *User
}

//nolint:gochecknoglobals // the principals are minted once per process
var (
	principalsOnce sync.Once
	principals     *Principals
	principalsErr  string
)

// People returns the run's owner, member and outsider.
func People(t testing.TB) *Principals {
	t.Helper()
	principalsOnce.Do(func() {
		inner := &onceT{TB: t}
		func() {
			defer func() {
				//nolint:errorlint // a recovered panic value, not a wrapped error
				if r := recover(); r != nil && r != errOnceFailed {
					panic(r)
				}
			}()
			principals = &Principals{
				Owner:    NewUser(inner, "owner"),
				Member:   NewUser(inner, "member"),
				Outsider: NewUser(inner, "outsider"),
			}
		}()
		principalsErr = inner.msg
	})
	if principalsErr != "" {
		t.Fatalf("minting principals: %s", principalsErr)
	}
	return principals
}

var errOnceFailed = fmt.Errorf("principals: failed")

// onceT records a failure inside a sync.Once instead of calling FailNow on
// whichever test happened to run first, so later tests report it too.
type onceT struct {
	testing.TB
	msg string
}

func (o *onceT) Helper() {}

func (o *onceT) Fatal(args ...any) {
	o.msg = fmt.Sprint(args...)
	panic(errOnceFailed)
}

func (o *onceT) Fatalf(format string, args ...any) {
	o.msg = fmt.Sprintf(format, args...)
	panic(errOnceFailed)
}
