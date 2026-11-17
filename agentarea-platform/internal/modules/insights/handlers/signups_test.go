package handlers

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/insights/service"
)

type hookRecorder struct {
	key    string
	hooks  []service.SignupHook
	method string
}

func (h *hookRecorder) CheckSignupKey(authorization string) error {
	return service.NewAnalytics(service.AnalyticsDeps{SignupHookKey: h.key}).CheckSignupKey(authorization)
}

func (h *hookRecorder) RecordSignup(_ context.Context, hook service.SignupHook, method string) error {
	h.hooks, h.method = append(h.hooks, hook), method
	return nil
}

func signupServer(t *testing.T, rec *hookRecorder) *httptest.Server {
	t.Helper()
	r := chi.NewRouter()
	MountSignups(r, httpx.NewErrors("http://api", slog.New(slog.DiscardHandler), MapError), rec)
	srv := httptest.NewServer(r)
	t.Cleanup(srv.Close)
	return srv
}

func post(t *testing.T, url, key, body string) (int, string) {
	t.Helper()
	req, _ := http.NewRequest(http.MethodPost, url, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	if key != "" {
		req.Header.Set("Authorization", key)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	b, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, string(b)
}

func TestSignupHookIsOffWithoutAKey(t *testing.T) {
	srv := signupServer(t, &hookRecorder{})
	if code, body := post(t, srv.URL+"/internal/analytics/signups", "anything", `{}`); code != http.StatusNotFound || !strings.Contains(body, "Not Found") {
		t.Fatal(code, body)
	}
}

func TestSignupHookNeedsTheKeyBeforeTheBody(t *testing.T) {
	srv := signupServer(t, &hookRecorder{key: "k"})
	if code, body := post(t, srv.URL+"/internal/analytics/signups", "wrong", `not json`); code != http.StatusUnauthorized || !strings.Contains(body, "Unauthorized") {
		t.Fatal(code, body)
	}
}

func TestSignupHookRecordsTheIdentity(t *testing.T) {
	rec := &hookRecorder{key: "k"}
	srv := signupServer(t, rec)
	code, body := post(t, srv.URL+"/internal/analytics/signups?method=oidc", "k",
		`{"identity_id":"id-1","created_at":"2026-11-17T10:00:00.5+03:00","request_url":"https://x/?utm_source=a"}`)
	if code != http.StatusNoContent || body != "" || len(rec.hooks) != 1 || rec.method != "oidc" {
		t.Fatal(code, body, rec.hooks)
	}
	h := rec.hooks[0]
	if h.IdentityID != "id-1" || !h.CreatedAt.Equal(time.Date(2026, 11, 17, 7, 0, 0, 5e8, time.UTC)) || h.RequestURL == nil {
		t.Fatalf("%+v", h)
	}
}

func TestSignupHookValidatesTheBody(t *testing.T) {
	srv := signupServer(t, &hookRecorder{key: "k"})
	for body, want := range map[string]string{
		`{"created_at":"2026-11-17T10:00:00Z"}`:                                                 `"missing"`,
		`{"identity_id":"","created_at":"2026-11-17T10:00:00Z"}`:                                `"string_too_short"`,
		`{"identity_id":"` + strings.Repeat("x", 65) + `","created_at":"2026-11-17T10:00:00Z"}`: `"string_too_long"`,
		`{"identity_id":"a","created_at":"yesterday"}`:                                          `"value_error"`,
		`{"identity_id":"a","created_at":"2026-11-17T10:00:00Z","request_url":1}`:               `"string_type"`,
	} {
		if code, got := post(t, srv.URL+"/internal/analytics/signups", "k", body); code != http.StatusUnprocessableEntity || !strings.Contains(got, want) {
			t.Errorf("%s: %d %s", body, code, got)
		}
	}
}
