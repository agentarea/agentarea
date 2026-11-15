package service

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
)

// Settings is GET /settings: the workspace's monthly spend cap, nil when
// none is set. Every member reads it.
func (s *Service) Settings(ctx context.Context, c authn.Caller) (*money.Decimal, error) {
	return s.d.Reads.Caps.MonthlyCap(ctx, c.Workspace)
}

// RequireAdmin refuses a caller who is not an admin of the workspace.
func (s *Service) RequireAdmin(ctx context.Context) error { return s.d.Admin(ctx) }

// SetSettings is PUT /settings for a workspace admin: nil removes the
// monthly cap. The caller checks the admin first, before reading the body.
func (s *Service) SetSettings(ctx context.Context, c authn.Caller, amount *money.Decimal) error {
	return s.d.Reads.Caps.SetMonthlyCap(ctx, c, amount)
}
