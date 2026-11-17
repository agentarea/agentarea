package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// CapRefused is a monthly cap the policy engine could not enforce; Detail is
// assert_enforceable's message.
type CapRefused struct{ Detail string }

func (e *CapRefused) Error() string { return e.Detail }

// SpendCaps is the workspace's monthly spend cap: a workspace-wide cap on
// spend for the calendar month, narrowed to no kind, client, connection,
// tool or currency (the workspace settings and the dashboard).
type SpendCaps interface {
	// MonthlyCap is the first enabled cap's amount_usd; nil when none is set.
	MonthlyCap(ctx context.Context, ws scope.Workspace) (*money.Decimal, error)
	// CapCurrencies is workspace_cap_currencies: the currencies the enabled
	// monthly workspace caps count, billing for a cap that declares none.
	CapCurrencies(ctx context.Context, ws scope.Workspace, billing string) (map[string]bool, error)
	// SetMonthlyCap replaces the cap as c, a workspace admin: nil removes
	// every monthly cap, a value updates the first and removes the rest or
	// creates one. A cap the engine cannot enforce is a *CapRefused.
	SetMonthlyCap(ctx context.Context, c authn.Caller, amount *money.Decimal) error
}
