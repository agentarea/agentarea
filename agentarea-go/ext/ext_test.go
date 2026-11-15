package ext

import (
	"context"
	"strings"
	"testing"
	"testing/fstest"
)

type usd struct{}

func (usd) Currency() Currency { return "USD" }

func pricing(context.Context, Deps) (CustomerPricing, error) { return usd{}, nil }

func apply(opts ...Option) *Set {
	s := &Set{}
	for _, o := range opts {
		o(s)
	}
	return s
}

func TestSingleValuedPointTwiceIsAnError(t *testing.T) {
	s := apply(WithCustomerPricing(pricing), WithCustomerPricing(pricing))
	if err := s.Err(); err == nil || !strings.Contains(err.Error(), "customer_pricing registered twice") {
		t.Fatalf("got %v", err)
	}
}

func TestNilFactoryIsAnError(t *testing.T) {
	if err := apply(WithToolBilling(nil)).Err(); err == nil {
		t.Fatal("nil factory accepted")
	}
}

func TestDuplicateSubcommandIsAnError(t *testing.T) {
	run := func(context.Context, Deps, []string) error { return nil }
	role := func(context.Context, Deps) error { return nil }
	s := apply(WithCommand(Command{Name: "rollup", Run: run}), WithRole(Role{Name: "rollup", Run: role}))
	if err := s.Err(); err == nil || !strings.Contains(err.Error(), `"rollup" registered twice`) {
		t.Fatalf("got %v", err)
	}
}

func TestMigrationSets(t *testing.T) {
	m := MigrationSet{Name: "enterprise", FS: fstest.MapFS{}, Schema: "agentarea_enterprise",
		AlembicTable: "agentarea_enterprise.alembic_version_enterprise", AlembicHead: "20261022_1200_ledger_monitor"}
	if err := apply(WithMigrations(m)).Err(); err != nil {
		t.Fatal(err)
	}
	if err := apply(WithMigrations(m), WithMigrations(m)).Err(); err == nil {
		t.Fatal("duplicate migration set accepted")
	}
	for name, bad := range map[string]MigrationSet{
		"no filesystem":    {Name: "x", Schema: "x"},
		"no schema":        {Name: "x", FS: fstest.MapFS{}},
		"public schema":    {Name: "x", FS: fstest.MapFS{}, Schema: "public"},
		"table, no head":   {Name: "x", FS: fstest.MapFS{}, Schema: "x", AlembicTable: "x.v"},
		"head, no table":   {Name: "x", FS: fstest.MapFS{}, Schema: "x", AlembicHead: "r1"},
		"nameless at head": {FS: fstest.MapFS{}, Schema: "x"},
	} {
		if err := apply(WithMigrations(bad)).Err(); err == nil {
			t.Errorf("%s: accepted", name)
		}
	}
}

func TestEveryPointRegisters(t *testing.T) {
	run := func(context.Context, Deps, []string) error { return nil }
	role := func(context.Context, Deps) error { return nil }
	routes := func(context.Context, Deps, Router) error { return nil }
	s := apply(
		WithEntitlementGuard(func(context.Context, Deps) (EntitlementGuard, error) { return nil, nil }),
		WithWorkspaceRoutes(routes), WithAccountRoutes(routes),
		WithCustomerPricing(pricing),
		WithAccountBalance(func(context.Context, Deps) (AccountBalanceSource, error) { return nil, nil }),
		WithWorkspaceUsage(func(context.Context, Deps) (WorkspaceUsageSource, error) { return nil, nil }),
		WithToolBilling(func(context.Context, Deps) (ToolBilling, error) { return nil, nil }),
		WithEgressExits(func(context.Context, Deps) (EgressExits, error) { return nil, nil }),
		WithAuditSink(func(context.Context, Deps) (AuditSink, error) { return nil, nil }),
		WithWorkloadHooks(func(context.Context, Deps) (WorkloadHooks, error) { return WorkloadHooks{}, nil }),
		WithCommand(Command{Name: "rollup", Run: run}),
		WithRole(Role{Name: "usage-emitter", Run: role}),
	)
	if err := s.Err(); err != nil {
		t.Fatal(err)
	}
	if s.EntitlementGuard == nil || s.AccountBalance == nil || s.WorkspaceUsage == nil || s.ToolBilling == nil ||
		s.EgressExits == nil || s.AuditSink == nil || len(s.WorkloadHooks) != 1 || len(s.AccountRoutes) != 1 ||
		len(s.Commands) != 1 || len(s.Roles) != 1 {
		t.Fatalf("set %+v", s)
	}
}

func TestValidSetHasNoError(t *testing.T) {
	routes := func(context.Context, Deps, Router) error { return nil }
	s := apply(WithCustomerPricing(pricing), WithWorkspaceRoutes(routes), WithAccountRoutes(routes))
	if err := s.Err(); err != nil || s.CustomerPricing == nil || len(s.WorkspaceRoutes) != 1 {
		t.Fatalf("got %v", err)
	}
}
