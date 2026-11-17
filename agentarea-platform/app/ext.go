package app

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"

	"github.com/agentarea/agentarea/agentarea-platform/ext"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/serve"
)

// workspaceSecrets is ext.WorkspaceSecrets over the core's secret backend,
// read in the secret's own workspace.
type workspaceSecrets struct {
	db      db.Database
	secrets *secrets.Factory
}

func (w workspaceSecrets) WorkspaceSecret(ctx context.Context, workspaceID, name string) (string, error) {
	ws, err := scope.NewWorkspace(workspaceID, "")
	if err != nil {
		return "", err
	}
	sess, release, err := w.db.Read(ctx, ws)
	if err != nil {
		return "", err
	}
	defer release()
	return w.secrets.Manager(sess, "").Get(ctx, name)
}

// extensions is what the build's single-valued and hook options built for
// one role. A point nobody registered is nil, except CustomerPricing, which
// is USD at provider cost; EgressExits says whether egress_exits was built.
type extensions struct {
	EntitlementGuard ext.EntitlementGuard
	CustomerPricing  ext.CustomerPricing
	AccountBalance   ext.AccountBalanceSource
	WorkspaceUsage   ext.WorkspaceUsageSource
	ToolBilling      ext.ToolBilling
	EgressExits      bool
	AuditSink        ext.AuditSink
	WorkloadHooks    []ext.WorkloadHooks

	closers []io.Closer
}

// Close closes every built value that is an io.Closer, last built first.
func (e *extensions) Close() error {
	var errs []error
	for i := len(e.closers) - 1; i >= 0; i-- {
		errs = append(errs, e.closers[i].Close())
	}
	e.closers = nil
	return errors.Join(errs...)
}

func build[T any](ctx context.Context, e *extensions, deps ext.Deps, point string, f ext.Factory[T]) (T, error) {
	var zero T
	if f == nil {
		return zero, nil
	}
	v, err := f(ctx, deps)
	if err != nil {
		return zero, fmt.Errorf("extension %s: %w", point, err)
	}
	if c, ok := any(v).(io.Closer); ok {
		e.closers = append(e.closers, c)
	}
	return v, nil
}

// resolveExtensions runs every factory once; the first failure stops the
// role (D9). Tool billing whose ledger is not in spend refuses to start
// (SpendCurrencyMismatchError, main.py:71-73).
func (b *Build) resolveExtensions(ctx context.Context, deps ext.Deps, spend money.Currency) (_ *extensions, err error) {
	s := &b.ext
	e := &extensions{}
	defer func() {
		if err != nil {
			err = errors.Join(err, e.Close())
		}
	}()
	if e.EntitlementGuard, err = build(ctx, e, deps, "entitlement_guard", s.EntitlementGuard); err != nil {
		return nil, err
	}
	if e.CustomerPricing, err = build(ctx, e, deps, "customer_pricing", s.CustomerPricing); err != nil {
		return nil, err
	}
	if s.CustomerPricing != nil && e.CustomerPricing == nil {
		return nil, errors.New("extension customer_pricing: the factory built nothing")
	}
	if e.CustomerPricing == nil {
		e.CustomerPricing = money.USDAtProviderCost{}
	}
	if e.AccountBalance, err = build(ctx, e, deps, "account_balance", s.AccountBalance); err != nil {
		return nil, err
	}
	if e.WorkspaceUsage, err = build(ctx, e, deps, "workspace_usage", s.WorkspaceUsage); err != nil {
		return nil, err
	}
	if e.ToolBilling, err = build(ctx, e, deps, "tool_billing", s.ToolBilling); err != nil {
		return nil, err
	}
	if e.ToolBilling != nil && e.ToolBilling.Currency() != spend {
		return nil, &money.SpendCurrencyMismatchError{Ledger: e.ToolBilling.Currency(), Configured: spend}
	}
	if s.EgressExits != nil {
		if _, err = build(ctx, e, deps, "egress_exits", s.EgressExits); err != nil {
			return nil, err
		}
		e.EgressExits = true
	}
	if e.AuditSink, err = build(ctx, e, deps, "audit_sink", s.AuditSink); err != nil {
		return nil, err
	}
	for _, f := range s.WorkloadHooks {
		h, err := build(ctx, e, deps, "workload hooks", f)
		if err != nil {
			return nil, err
		}
		e.WorkloadHooks = append(e.WorkloadHooks, h)
	}
	return e, nil
}

// extensionEdge is what the serve edge lends extension routes: the
// middleware that admits the caller of /v1/workspaces/{workspace}, the one
// that resolves a principal (401 without), and the workspace admin check.
type extensionEdge struct {
	Workspace    httpx.Middleware
	Authenticate httpx.Middleware
	RequireAdmin func(ctx context.Context, c authn.Caller) error
}

// workspacePrefix is WORKSPACE_PREFIX, where workspace_api_router mounts.
const workspacePrefix = "/v1/workspaces/{" + httpx.WorkspaceParam + "}"

// extensionModules mounts the route extensions after every core module, so
// none shadows a core path: workspace routes under workspacePrefix behind
// edge.Workspace, account routes as declared.
func (b *Build) extensionModules(ctx context.Context, deps ext.Deps, edge extensionEdge) []serve.Module {
	var mods []serve.Module
	routeDeps := func(rt serve.Routes) ext.Deps {
		d := deps
		d.Errors, d.Authenticate, d.RequireAdmin = rt.Errors, edge.Authenticate, edge.RequireAdmin
		return d
	}
	for i, f := range b.ext.WorkspaceRoutes {
		mods = append(mods, serve.Module{
			Name: fmt.Sprintf("ext workspace routes %d", i+1),
			Mount: func(rt serve.Routes) error {
				if edge.Workspace == nil {
					return errors.New("workspace routes need the workspace edge, which this build has not got")
				}
				return f(ctx, routeDeps(rt), wrapped{r: rt.Mux.Group(workspacePrefix), mw: edge.Workspace})
			},
		})
	}
	for i, f := range b.ext.AccountRoutes {
		mods = append(mods, serve.Module{
			Name:  fmt.Sprintf("ext account routes %d", i+1),
			Mount: func(rt serve.Routes) error { return f(ctx, routeDeps(rt), rt.Mux) },
		})
	}
	return mods
}

type wrapped struct {
	r  httpx.Router
	mw httpx.Middleware
}

func (w wrapped) Handle(pattern string, h http.Handler) { w.r.Handle(pattern, w.mw(h)) }

// ExtensionDeps opens what a factory, command or role of an extension gets
// outside serve: the logger, configuration and the core's database. close
// releases the database. Commands and roles get these; an extension module's
// tests use it to build the same values app builds.
func (b *Build) ExtensionDeps(ctx context.Context) (deps ext.Deps, closeDeps func(), err error) {
	l := config.New(b.lookup)
	common := config.LoadCommon(l)
	dbc := db.LoadConfig(l)
	if err := l.Err(); err != nil {
		return ext.Deps{}, nil, fmt.Errorf("configuration: %w", err)
	}
	log := newLogger(b.stderr, common)
	pools, err := db.Open(ctx, dbc, log)
	if err != nil {
		return ext.Deps{}, nil, fmt.Errorf("database: %w", err)
	}
	return ext.Deps{Logger: log, Config: config.New(b.lookup), DB: pools}, pools.Close, nil
}
