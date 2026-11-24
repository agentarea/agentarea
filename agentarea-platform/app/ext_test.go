package app

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strings"
	"testing"
	"testing/fstest"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/ext"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/schema"
	"github.com/agentarea/agentarea/agentarea-platform/internal/serve"
)

type rub struct{ closed *int }

func (rub) Currency() ext.Currency { return "RUB" }

func (r rub) Close() error {
	if r.closed != nil {
		*r.closed++
	}
	return nil
}

type rubBilling struct{ ext.ToolBilling }

func (rubBilling) Currency() ext.Currency { return "RUB" }

func TestResolveDefaultsPricingToUSD(t *testing.T) {
	b, _ := quiet()
	e, err := b.resolveExtensions(context.Background(), ext.Deps{}, "USD")
	if err != nil {
		t.Fatal(err)
	}
	if e.CustomerPricing.Currency() != "USD" || e.ToolBilling != nil || e.EntitlementGuard != nil {
		t.Fatalf("got %+v", e)
	}
}

func TestResolveRefusesToolBillingInAnotherCurrency(t *testing.T) {
	b, _ := quiet(ext.WithToolBilling(func(context.Context, ext.Deps) (ext.ToolBilling, error) { return rubBilling{}, nil }))
	_, err := b.resolveExtensions(context.Background(), ext.Deps{}, "USD")
	var mismatch *money.SpendCurrencyMismatchError
	if !errors.As(err, &mismatch) || mismatch.Ledger != "RUB" || mismatch.Configured != "USD" {
		t.Fatalf("got %v", err)
	}
	if _, err := b.resolveExtensions(context.Background(), ext.Deps{}, "RUB"); err != nil {
		t.Fatal(err)
	}
}

func TestFailingFactoryStopsAndClosesWhatWasBuilt(t *testing.T) {
	closed := 0
	b, _ := quiet(
		ext.WithCustomerPricing(func(context.Context, ext.Deps) (ext.CustomerPricing, error) { return rub{&closed}, nil }),
		ext.WithAccountBalance(func(context.Context, ext.Deps) (ext.AccountBalanceSource, error) {
			return nil, errors.New("billing unreachable")
		}),
	)
	_, err := b.resolveExtensions(context.Background(), ext.Deps{}, "RUB")
	if err == nil || !strings.Contains(err.Error(), "account_balance: billing unreachable") || closed != 1 {
		t.Fatalf("got %v, closed %d", err, closed)
	}
}

func assemble(t *testing.T, mods ...serve.Module) http.Handler {
	t.Helper()
	l := config.FromMap(nil)
	a, err := serve.Assemble(serve.LoadConfig(l), serve.Options{}, slog.New(slog.DiscardHandler), mods...)
	if err != nil {
		t.Fatal(err)
	}
	return a.Handler
}

func TestWorkspaceRoutesNeedTheWorkspaceEdge(t *testing.T) {
	routes := func(context.Context, ext.Deps, ext.Router) error { return nil }
	b, _ := quiet(ext.WithWorkspaceRoutes(routes))
	l := config.FromMap(nil)
	_, err := serve.Assemble(serve.LoadConfig(l), serve.Options{}, slog.New(slog.DiscardHandler),
		b.extensionModules(context.Background(), ext.Deps{}, extensionEdge{})...)
	if err == nil || !strings.Contains(err.Error(), "workspace edge") {
		t.Fatalf("got %v", err)
	}
}

func TestExtensionRoutesMount(t *testing.T) {
	var gotDeps ext.Deps
	ws := func(_ context.Context, d ext.Deps, r ext.Router) error {
		gotDeps = d
		r.Handle("GET /billing/overview", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			c, ok := ext.CallerFrom(r.Context())
			if !ok {
				d.Errors.Write(w, r, ext.HTTPError(http.StatusServiceUnavailable, "no caller"))
				return
			}
			_, _ = w.Write([]byte(c.Workspace.ID() + " " + r.PathValue("workspace")))
		}))
		return nil
	}
	account := func(_ context.Context, d ext.Deps, r ext.Router) error {
		r.Handle("GET /v1/billing/pending-payments", d.Authenticate(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			p, _ := ext.PrincipalFrom(r.Context())
			_, _ = w.Write([]byte(p.UserID))
		})))
		return nil
	}
	edge := extensionEdge{
		Workspace: func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w2, _ := scope.NewWorkspace("ws-1", r.PathValue("workspace"))
				ctx := authn.WithCaller(r.Context(), authn.Caller{Principal: authn.Principal{UserID: "u1"}, Workspace: w2})
				next.ServeHTTP(w, r.WithContext(ctx))
			})
		},
		Authenticate: func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				next.ServeHTTP(w, r.WithContext(authn.WithPrincipal(r.Context(), authn.Principal{UserID: "u2"})))
			})
		},
		RequireAdmin: func(context.Context, authn.Caller) error { return nil },
	}
	b, _ := quiet(ext.WithWorkspaceRoutes(ws), ext.WithAccountRoutes(account))
	h := assemble(t, b.extensionModules(context.Background(), ext.Deps{}, edge)...)
	if gotDeps.Errors == nil || gotDeps.Authenticate == nil || gotDeps.RequireAdmin == nil {
		t.Fatalf("route deps %+v", gotDeps)
	}
	for path, want := range map[string]string{
		"/v1/workspaces/acme/billing/overview": "ws-1 acme",
		"/v1/billing/pending-payments":         "u2",
	} {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
		if rec.Code != http.StatusOK || rec.Body.String() != want {
			t.Errorf("%s: %d %q", path, rec.Code, rec.Body.String())
		}
	}
}

func TestMigrationSetsFollowTheCore(t *testing.T) {
	m := ext.MigrationSet{Name: "enterprise", FS: fstest.MapFS{}, Schema: "agentarea_enterprise",
		AlembicTable: "agentarea_enterprise.alembic_version_enterprise", AlembicHead: "r9"}
	b, _ := quiet(ext.WithMigrations(m))
	sets := b.migrationSets()
	if len(sets) != 2 || sets[0].Name != "core" {
		t.Fatalf("sets %+v", sets)
	}
	e := sets[1]
	if e.VersionTable != "agentarea_enterprise.goose_db_version" || !e.CreateSchema || e.AlembicHead != "r9" ||
		e.LockKey != "agentarea_schema_enterprise" {
		t.Fatalf("enterprise set %+v", e)
	}
}

// TestMigrateAppliesCoreThenExtensions needs AGENTAREA_DB_TEST_URL.
func TestMigrateAppliesCoreThenExtensions(t *testing.T) {
	raw := os.Getenv("AGENTAREA_DB_TEST_URL")
	if raw == "" {
		t.Skip("AGENTAREA_DB_TEST_URL not set")
	}
	u, err := url.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	admin, err := schema.Open(raw)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = admin.Close() }()
	name := "aa_go_app_" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
	if _, err := admin.ExecContext(ctx, "CREATE DATABASE "+name); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _, _ = admin.ExecContext(ctx, "DROP DATABASE "+name+" WITH (FORCE)") })

	set := ext.MigrationSet{Name: "extra", Schema: "agentarea_extra", FS: fstest.MapFS{
		"00001_t.sql": {Data: []byte("-- +goose Up\nCREATE TABLE agentarea_extra.t (workspace_id text REFERENCES public.workspaces (id));\n")},
	}}
	b, _ := quiet(ext.WithMigrations(set))
	pw, _ := u.User.Password()
	b.lookup = mapLookup(map[string]string{
		"AGENTAREA_DB_HOST": u.Hostname(), "AGENTAREA_DB_PORT": u.Port(), "AGENTAREA_DB_NAME": name,
		"AGENTAREA_DB_USER": u.User.Username(), "AGENTAREA_DB_PASSWORD": pw, "AGENTAREA_DB_SSLMODE": "disable",
	})
	if err := b.Run(ctx, []string{"check-migrations"}); !errors.Is(err, ErrMigrationsPending) {
		t.Fatalf("check-migrations on an empty database: %v", err)
	}
	for range 2 {
		if err := b.Run(ctx, []string{"migrate"}); err != nil {
			t.Fatal(err)
		}
	}
	if err := b.Run(ctx, []string{"check-migrations"}); err != nil {
		t.Fatalf("check-migrations after migrate: %v", err)
	}
	u.Path = "/" + name
	conn, err := schema.Open(u.String())
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = conn.Close() }()
	var n int
	if err := conn.QueryRowContext(ctx, "SELECT count(*) FROM agentarea_extra.goose_db_version WHERE version_id = 1").Scan(&n); err != nil || n != 1 {
		t.Fatalf("extension set not applied: %d %v", n, err)
	}
	if err := conn.QueryRowContext(ctx, "SELECT count(*) FROM graph_migrations WHERE id = '20261109_2300_secret_owners'").Scan(&n); err != nil || n != 1 {
		t.Fatalf("graph migration not recorded: %d %v", n, err)
	}
}
