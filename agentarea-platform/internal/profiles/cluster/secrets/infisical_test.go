package secrets

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	kernel "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
)

type fakeInfisical struct {
	mu      sync.Mutex
	secrets map[string]string // path+"/"+name -> value
	logins  int
	status  int // forces a status on secret calls when set
}

func (f *fakeInfisical) handler(t *testing.T) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.mu.Lock()
		defer f.mu.Unlock()
		if r.URL.Path == "/api/v1/auth/universal-auth/login" {
			var in map[string]string
			_ = json.NewDecoder(r.Body).Decode(&in)
			if in["clientId"] != "cid" || in["clientSecret"] != "csec" {
				w.WriteHeader(http.StatusUnauthorized)
				return
			}
			f.logins++
			_ = json.NewEncoder(w).Encode(map[string]any{"accessToken": "tok", "expiresIn": 3600})
			return
		}
		if r.Header.Get("Authorization") != "Bearer tok" {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		if f.status != 0 {
			w.WriteHeader(f.status)
			return
		}
		name := strings.TrimPrefix(r.URL.Path, "/api/v3/secrets/raw/")
		var path, project, env string
		var value string
		if r.Method == http.MethodGet {
			q := r.URL.Query()
			path, project, env = q.Get("secretPath"), q.Get("projectId"), q.Get("environment")
		} else {
			var in map[string]any
			_ = json.NewDecoder(r.Body).Decode(&in)
			path, _ = in["secretPath"].(string)
			project, _ = in["projectId"].(string)
			env, _ = in["environment"].(string)
			value, _ = in["secretValue"].(string)
		}
		if project != "proj" || env != "prod" {
			t.Errorf("project/env: %q %q", project, env)
		}
		key := path + "/" + name
		switch r.Method {
		case http.MethodGet:
			v, ok := f.secrets[key]
			if !ok {
				w.WriteHeader(http.StatusNotFound)
				return
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"secret": map[string]any{"secretValue": v}})
		case http.MethodPost:
			f.secrets[key] = value
			_, _ = w.Write([]byte(`{}`))
		case http.MethodPatch:
			if _, ok := f.secrets[key]; !ok {
				w.WriteHeader(http.StatusNotFound)
				return
			}
			f.secrets[key] = value
			_, _ = w.Write([]byte(`{}`))
		case http.MethodDelete:
			delete(f.secrets, key)
			_, _ = w.Write([]byte(`{}`))
		}
	})
}

func newInfisical(t *testing.T) (*InfisicalClient, *fakeInfisical) {
	f := &fakeInfisical{secrets: map[string]string{}}
	srv := httptest.NewServer(f.handler(t))
	t.Cleanup(srv.Close)
	c := NewInfisicalClient(kernel.Config{Endpoint: srv.URL + "/", ClientID: "cid", ClientSecret: "csec", ProjectID: "proj", Env: "prod"}, nil)
	return c, f
}

func TestInfisicalBackend(t *testing.T) {
	c, fake := newInfisical(t)
	ctx := context.Background()
	a, b := c.ForWorkspace("wsA"), c.ForWorkspace("wsB")

	if _, err := a.Get(ctx, "k"); !errors.Is(err, kernel.ErrNotFound) {
		t.Fatalf("missing: %v", err)
	}
	if err := a.Set(ctx, "k", "one"); err != nil {
		t.Fatal(err)
	}
	if err := a.Set(ctx, "k", "two"); err != nil {
		t.Fatal(err)
	}
	if v, err := a.Get(ctx, "k"); err != nil || v != "two" {
		t.Errorf("%q %v", v, err)
	}
	if _, err := b.Get(ctx, "k"); !errors.Is(err, kernel.ErrNotFound) {
		t.Errorf("workspace B reads A's secret: %v", err)
	}
	if _, ok := fake.secrets["/workspaces/wsA/k"]; !ok {
		t.Errorf("path: %v", fake.secrets)
	}
	if ref, ok := a.ExternalRef("k"); !ok || ref != "infisical://proj/prod/workspaces/wsA/k" {
		t.Errorf("ref %q %v", ref, ok)
	}
	if ok, _ := a.Has(ctx, "k"); !ok {
		t.Error("Has")
	}
	if gone, err := a.Delete(ctx, "k"); err != nil || !gone {
		t.Errorf("delete %v %v", gone, err)
	}
	if gone, err := a.Delete(ctx, "k"); err != nil || gone {
		t.Errorf("second delete %v %v", gone, err)
	}
	if fake.logins != 1 {
		t.Errorf("token not reused: %d logins", fake.logins)
	}
}

func TestInfisicalOnlyAbsenceIsNotFound(t *testing.T) {
	c, fake := newInfisical(t)
	fake.status = http.StatusInternalServerError
	_, err := c.ForWorkspace("w").Get(context.Background(), "k")
	if err == nil || errors.Is(err, kernel.ErrNotFound) {
		t.Errorf("a backend that could not answer must not read as absence: %v", err)
	}
	fake.status = http.StatusForbidden
	if _, err := c.ForWorkspace("w").Get(context.Background(), "k"); errors.Is(err, kernel.ErrNotFound) || err == nil {
		t.Errorf("403: %v", err)
	}
}

func TestInfisicalRejectedIdentity(t *testing.T) {
	c, _ := newInfisical(t)
	c.clientSecret = "wrong"
	_, err := c.ForWorkspace("w").Get(context.Background(), "k")
	if err == nil || strings.Contains(err.Error(), "wrong") {
		t.Errorf("%v", err)
	}
}

func TestFactoryBackends(t *testing.T) {
	if _, err := NewFactory(kernel.Config{Backend: "vault"}, nil); err == nil {
		t.Error("unknown backend accepted")
	}
	if _, err := NewFactory(kernel.Config{Backend: kernel.BackendDatabase, EncryptionKey: "bad"}, nil); err == nil || strings.Contains(err.Error(), "bad\"") {
		t.Errorf("bad key: %v", err)
	}
	f, err := NewFactory(kernel.Config{Backend: kernel.BackendInfisical, Endpoint: "http://x", ClientID: "a", ClientSecret: "b", ProjectID: "p", Env: "prod"}, nil)
	if err != nil || f.Backend() != "infisical" {
		t.Errorf("%v", err)
	}
}
