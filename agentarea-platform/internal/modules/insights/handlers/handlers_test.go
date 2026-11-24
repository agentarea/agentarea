package handlers

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/insights/service"
)

type fakeDB struct{ db.Database }

func (fakeDB) Global() db.Global { return nil }

type fakeInstallations struct{ calls int }

func (f *fakeInstallations) GetOrCreate(context.Context, db.Global, time.Time) (string, error) {
	f.calls++
	return "install-1", nil
}

type fakeBalance struct {
	b   money.AccountBalance
	err error
}

func (f fakeBalance) Balance(context.Context, authn.Caller) (money.AccountBalance, error) {
	return f.b, f.err
}

// server mounts the routes over svc; the edge admits every request as a member.
func server(t *testing.T, svc *service.Service) *httptest.Server {
	t.Helper()
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	p := authn.Principal{UserID: "member"}
	workspace := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			next.ServeHTTP(w, r.WithContext(authn.WithCaller(r.Context(), authn.Caller{Principal: p, Workspace: ws})))
		})
	}
	principal := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			next.ServeHTTP(w, r.WithContext(authn.WithPrincipal(r.Context(), p)))
		})
	}
	errs := httpx.NewErrors("http://api", slog.New(slog.DiscardHandler), func(err error) (*httpx.Error, bool) {
		if errors.Is(err, authz.ErrNotWorkspaceAdmin) {
			return httpx.HTTPError(http.StatusForbidden, "Only a workspace admin may perform this action"), true
		}
		return MapError(err)
	})
	r := chi.NewRouter()
	Mount(r, errs, workspace, principal, New(svc))
	srv := httptest.NewServer(r)
	t.Cleanup(srv.Close)
	return srv
}

func get(t *testing.T, srv *httptest.Server, path string) (int, string) {
	t.Helper()
	resp, err := http.Get(srv.URL + path)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	b, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, string(b)
}

func svc(d service.Deps) *service.Service {
	d.DB = fakeDB{}
	d.Log = slog.New(slog.DiscardHandler)
	return service.New(d)
}

func TestAnalyticsOffIsNulls(t *testing.T) {
	inst := &fakeInstallations{}
	srv := server(t, svc(service.Deps{Installations: inst}))
	code, body := get(t, srv, "/v1/analytics")
	want := `{"enabled":false,"install_id":null,"collector_url":null,"edition":null}`
	if code != http.StatusOK || body != want || inst.calls != 0 {
		t.Fatalf("got %d %s (installations %d)", code, body, inst.calls)
	}
}

func TestAnalyticsOnReturnsInstallation(t *testing.T) {
	srv := server(t, svc(service.Deps{Installations: &fakeInstallations{}, AnalyticsEnabled: true, Edition: "oss"}))
	code, body := get(t, srv, "/v1/analytics")
	want := `{"enabled":true,"install_id":"install-1","collector_url":"https://analytics.agentarea.ai","edition":"oss"}`
	if code != http.StatusOK || body != want {
		t.Fatalf("got %d %s", code, body)
	}
}

func TestBalanceWithoutSourceIsNull(t *testing.T) {
	srv := server(t, svc(service.Deps{}))
	code, body := get(t, srv, "/v1/workspaces/acme/balance")
	if code != http.StatusOK || body != "null" {
		t.Fatalf("got %d %s", code, body)
	}
}

func TestBalanceForPayerShowsAmounts(t *testing.T) {
	amt, spend, runway := money.MustParse("42.00"), money.MustParse("2.10"), money.MustParse("20")
	src := fakeBalance{b: money.AccountBalance{Currency: "USD", ViewerIsPayer: true, Amount: &amt, SpendPerDay: &spend, RunwayDays: &runway}}
	srv := server(t, svc(service.Deps{Balance: src}))
	code, body := get(t, srv, "/v1/workspaces/acme/balance")
	want := `{"currency":"USD","exhausted":false,"viewer_is_payer":true,"amount":"42.00","spend_per_day":"2.10","runway_days":"20"}`
	if code != http.StatusOK || body != want {
		t.Fatalf("got %d %s", code, body)
	}
}

func TestBalanceSourceFailureIs503(t *testing.T) {
	srv := server(t, svc(service.Deps{Balance: fakeBalance{err: errors.New("db down")}}))
	code, body := get(t, srv, "/v1/workspaces/acme/balance")
	if code != http.StatusServiceUnavailable || !strings.Contains(body, "balance is unavailable") {
		t.Fatalf("got %d %s", code, body)
	}
}
