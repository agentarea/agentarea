// Package insights is the insights module: the installation record, usage
// analytics, the account balance, the dashboard, an agent's overview, the
// workspace spend cap and the network graph.
package insights

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/analytics"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/lifecycle"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/insights/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/insights/handlers"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/insights/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/insights/store"
	"github.com/agentarea/agentarea/agentarea-platform/internal/serve"
)

// Deps are what insights needs from other modules and the kernel, as interfaces
// declared in its service/deps.go; app passes them in (rule 2).
type Deps struct {
	DB db.Database
	// Balance is the account_balance extension; nil when the deployment sells none.
	Balance service.Balance
	// Config is what LoadConfig read at startup.
	Config Config
	// Workspace admits the caller into /v1/workspaces/{workspace}; Principal
	// authenticates a route that acts on no workspace.
	Workspace func(http.Handler) http.Handler
	Principal func(http.Handler) http.Handler
	// Admin is nil for a workspace admin of the caller's workspace and
	// authz.ErrNotWorkspaceAdmin otherwise.
	Admin func(ctx context.Context) error
	Now   func() time.Time
	Log   *slog.Logger
	// Counter is the process's analytics counter handle the started sender is attached to.
	Counter *analytics.Handle
	// Collector is the vendor transport analytics batches are posted over.
	Collector http.RoundTripper
	// Version is the build's version every analytics event carries.
	Version string
}

// Later are the reads of modules app builds after insights (runs, streams,
// wallet and the rest); Use sets them.
type Later = service.Reads

// Module is insights, constructed once per process; a role picks which of its
// parts run.
type Module struct {
	d     Deps
	later *Later
	svc   *service.Service
	an    *service.Analytics
}

// New constructs the module.
func New(d Deps) *Module {
	m := &Module{d: d}
	m.build()
	m.an = service.NewAnalytics(service.AnalyticsDeps{
		DB: d.DB, Installations: store.Installation{}, Lock: store.Installation{}, Signups: store.Signups{},
		Collector: store.Collector{URL: domain.CollectorURL, Transport: d.Collector}, Counter: d.Counter,
		Pulse: func() service.PulseReads {
			if m.later == nil {
				return service.PulseReads{}
			}
			return m.later.Pulse
		},
		Enabled: d.Config.AnalyticsEnabled, Version: d.Version, Edition: d.Config.Edition,
		SignupHookKey: d.Config.SignupHookKey, OwnDomains: d.Config.OwnDomains, Now: d.Now, Log: d.Log,
	})
	return m
}

// AnalyticsSender is start_analytics and stop_analytics: off, or failing to start, it sends
// nothing and fails nothing; on, it sends hourly and once more at stop.
func (m *Module) AnalyticsSender() lifecycle.Component {
	return lifecycle.Func("analytics sender", m.an.Start, m.an.Stop)
}

// InstallationPulse is the daily pulse: every replica ticks hourly, the one holding the lock sends.
// Add it after AnalyticsSender; without a started sender it sends nothing.
func (m *Module) InstallationPulse() lifecycle.Component {
	return lifecycle.Loop("installation pulse", func(ctx context.Context) error { return m.an.RunPulse(ctx, service.PulseTick) })
}

// Use sets the reads of modules built after insights; call it before serving.
func (m *Module) Use(l Later) {
	m.later = &l
	m.build()
}

func (m *Module) build() {
	d := m.d
	var reads service.Reads
	if m.later != nil {
		reads = *m.later
	}
	m.svc = service.New(service.Deps{
		DB: d.DB, Installations: store.Installation{}, Balance: d.Balance, Reads: reads, Admin: d.Admin,
		AnalyticsEnabled: d.Config.AnalyticsEnabled, Edition: d.Config.Edition, Now: d.Now, Log: d.Log,
	})
}

// errNotWired is serving before app called Use.
var errNotWired = errors.New("insights: Use was not called before serving")

// Name is the module's name in the role table.
func (*Module) Name() string { return "insights" }

// Serve is the module's HTTP surface: every operation of its spec but GET
// /health. Mounting fails until Use set the other modules' reads.
func (m *Module) Serve() serve.Module {
	return serve.Module{
		Name:   m.Name(),
		Errors: handlers.MapError,
		Mount: func(rt serve.Routes) error {
			if m.later == nil || m.d.Admin == nil {
				return errNotWired
			}
			handlers.Mount(rt.Mux.Chi(), rt.Errors, m.d.Workspace, m.d.Principal, handlers.New(m.svc))
			handlers.MountSignups(rt.Mux.Chi(), rt.Errors, m.an)
			return nil
		},
	}
}
