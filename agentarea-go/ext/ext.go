// Package ext is the public extension surface of the open core.
//
// The enterprise build is its own Go module with its own cmd/agentarea
// (agentarea-enterprise/platform):
//
//	func main() {
//		os.Exit(app.Main(app.Default(
//			ext.WithEntitlementGuard(entitlement.New),
//			ext.WithWorkspaceRoutes(billingroutes.WorkspaceRoutes),
//			ext.WithAccountRoutes(billingroutes.AccountRoutes),
//			ext.WithCustomerPricing(pricing.New),
//			ext.WithToolBilling(toolbilling.New),
//			ext.WithMigrations(migrations.Set()),
//			ext.WithRole(emitter.Role()),
//			ext.WithCommand(rollup.Command()),
//		)))
//	}
//
// Every option replaces one Python extension point (entry point group
// agentarea.extensions) or one hook of the mcp-manager overlay. All are
// additive: present means active. A factory runs once at startup and a
// failing factory stops the process (D9); registering a single-valued point
// twice is a startup error. The selector points "permissions" and
// "authorization" have no implementer and are not ported (D8).
package ext

import (
	"context"
	"errors"
	"fmt"
)

// Option registers one extension.
type Option func(*Set)

// Factory builds an extension once, at startup, after configuration loaded.
// A built value that is also an io.Closer is closed when the role stops.
type Factory[T any] func(ctx context.Context, deps Deps) (T, error)

// RouteFactory contributes HTTP routes. Workspace routes are mounted under
// /v1/workspaces/{workspace} with the workspace resolved (CallerFrom gives
// the caller); account routes are mounted as declared with no auth added.
// Both are mounted after core routes, so an extension cannot shadow a core
// path.
type RouteFactory func(ctx context.Context, deps Deps, r Router) error

// Set is what the options registered. app reads it; nothing else does.
type Set struct {
	EntitlementGuard Factory[EntitlementGuard]
	WorkspaceRoutes  []RouteFactory
	AccountRoutes    []RouteFactory
	CustomerPricing  Factory[CustomerPricing]
	AccountBalance   Factory[AccountBalanceSource]
	WorkspaceUsage   Factory[WorkspaceUsageSource]
	ToolBilling      Factory[ToolBilling]
	EgressExits      Factory[EgressExits]
	AuditSink        Factory[AuditSink]
	WorkloadHooks    []Factory[WorkloadHooks]
	Migrations       []MigrationSet
	Commands         []Command
	Roles            []Role

	errs []error
}

// Err reports invalid registrations: a single-valued point registered twice,
// a nil factory, a nameless or duplicate command, role or migration set.
func (s *Set) Err() error { return errors.Join(s.errs...) }

func (s *Set) fail(format string, args ...any) { s.errs = append(s.errs, fmt.Errorf(format, args...)) }

func single[T any](s *Set, point string, slot *Factory[T], f Factory[T]) {
	switch {
	case f == nil:
		s.fail("ext: %s registered with a nil factory", point)
	case *slot != nil:
		s.fail("ext: %s registered twice", point)
	default:
		*slot = f
	}
}

// WithEntitlementGuard replaces entry point "entitlement_guard": a plan
// entitlement gate in the governance pipeline at PRE_LLM_CALL, priority 120
// (agentarea_governance/factory.py).
func WithEntitlementGuard(f Factory[EntitlementGuard]) Option {
	return func(s *Set) { single(s, "entitlement_guard", &s.EntitlementGuard, f) }
}

// WithWorkspaceRoutes replaces entry point "workspace_api_router".
func WithWorkspaceRoutes(f RouteFactory) Option {
	return func(s *Set) {
		if f == nil {
			s.fail("ext: workspace_api_router registered with a nil factory")
			return
		}
		s.WorkspaceRoutes = append(s.WorkspaceRoutes, f)
	}
}

// WithAccountRoutes replaces entry point "api_router": routes that act on no
// workspace, such as /v1/billing/pending-payments.
func WithAccountRoutes(f RouteFactory) Option {
	return func(s *Set) {
		if f == nil {
			s.fail("ext: api_router registered with a nil factory")
			return
		}
		s.AccountRoutes = append(s.AccountRoutes, f)
	}
}

// WithCustomerPricing replaces entry point "customer_pricing": the billing
// currency and, when the value is also a ComputePricing, the price of an hour
// of compute. Without it: USD at provider cost. Installed, it must resolve or
// the process does not start.
func WithCustomerPricing(f Factory[CustomerPricing]) Option {
	return func(s *Set) { single(s, "customer_pricing", &s.CustomerPricing, f) }
}

// WithAccountBalance replaces entry point "account_balance".
func WithAccountBalance(f Factory[AccountBalanceSource]) Option {
	return func(s *Set) { single(s, "account_balance", &s.AccountBalance, f) }
}

// WithWorkspaceUsage replaces entry point "workspace_usage".
func WithWorkspaceUsage(f Factory[WorkspaceUsageSource]) Option {
	return func(s *Set) { single(s, "workspace_usage", &s.WorkspaceUsage, f) }
}

// WithToolBilling replaces entry point "tool_billing": hold, capture, void and
// quote for calls on the platform's key. Its ledger currency must equal
// AGENTAREA_SPEND_CURRENCY or the process does not start.
func WithToolBilling(f Factory[ToolBilling]) Option {
	return func(s *Set) { single(s, "tool_billing", &s.ToolBilling, f) }
}

// WithEgressExits replaces entry point "egress_exits" (presence enables the
// egress exits API; absence answers 404 and no instance may bind an exit) and
// the EgressEnforcer swap of ports/egress_enforcer.py.
func WithEgressExits(f Factory[EgressExits]) Option {
	return func(s *Set) { single(s, "egress_exits", &s.EgressExits, f) }
}

// WithAuditSink replaces the "audit_sink" lookup (audit/service.py): every
// recorded audit event is also forwarded to the sink.
func WithAuditSink(f Factory[AuditSink]) Option {
	return func(s *Set) { single(s, "audit_sink", &s.AuditSink, f) }
}

// WithWorkloadHooks replaces mcp-manager's managerapp Options (ControlPlane
// hooks and DataPlane routes) and sandbox-runner's runner configuration, used
// by the enterprise overlay of both.
func WithWorkloadHooks(f Factory[WorkloadHooks]) Option {
	return func(s *Set) {
		if f == nil {
			s.fail("ext: workload hooks registered with a nil factory")
			return
		}
		s.WorkloadHooks = append(s.WorkloadHooks, f)
	}
}

// WithMigrations registers an embedded migration set
// (agentarea_enterprise/migrations, agentarea-enterprise-migrate). agentarea
// migrate applies it after the core set, against the same database, with its
// own version table.
func WithMigrations(m MigrationSet) Option {
	return func(s *Set) {
		switch {
		case m.Name == "" || m.FS == nil:
			s.fail("ext: migration set needs a name and a filesystem")
		case m.Schema == "" || m.Schema == "public":
			s.fail("ext: migration set %q needs a schema of its own", m.Name)
		case (m.AlembicTable == "") != (m.AlembicHead == ""):
			s.fail("ext: migration set %q names an Alembic table without a head, or a head without a table", m.Name)
		case hasMigrationSet(s.Migrations, m.Name):
			s.fail("ext: migration set %q registered twice", m.Name)
		default:
			s.Migrations = append(s.Migrations, m)
		}
	}
}

// WithCommand adds a one-shot subcommand, such as the enterprise console
// scripts compact-storage, rollup and ledger-partitions.
func WithCommand(c Command) Option {
	return func(s *Set) {
		switch {
		case c.Name == "" || c.Run == nil:
			s.fail("ext: command needs a name and a Run")
		case s.named(c.Name):
			s.fail("ext: subcommand %q registered twice", c.Name)
		default:
			s.Commands = append(s.Commands, c)
		}
	}
}

// WithRole adds a long-running role with its own deployment, such as the
// enterprise usage emitter.
func WithRole(r Role) Option {
	return func(s *Set) {
		switch {
		case r.Name == "" || r.Run == nil:
			s.fail("ext: role needs a name and a Run")
		case s.named(r.Name):
			s.fail("ext: subcommand %q registered twice", r.Name)
		default:
			s.Roles = append(s.Roles, r)
		}
	}
}

func (s *Set) named(name string) bool {
	for _, c := range s.Commands {
		if c.Name == name {
			return true
		}
	}
	for _, r := range s.Roles {
		if r.Name == name {
			return true
		}
	}
	return false
}

func hasMigrationSet(sets []MigrationSet, name string) bool {
	for _, m := range sets {
		if m.Name == name {
			return true
		}
	}
	return false
}
