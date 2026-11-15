package service

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/insights/domain"
)

// ErrBalanceUnavailable is a balance source that failed (503 "balance is unavailable").
var ErrBalanceUnavailable = errors.New("balance is unavailable")

// ErrNotPorted marks an operation of the insights OpenAPI spec the strict
// server never serves (GET /health, and PUT /settings, served raw).
var ErrNotPorted = errors.New("insights: operation not served here")

// Service is insights' use cases.
type Service struct {
	d Deps
}

// New builds the service.
func New(d Deps) *Service {
	if d.Now == nil {
		d.Now = time.Now
	}
	return &Service{d: d}
}

// Analytics is GET /v1/analytics. Off, no table is touched; on, the one
// installation row is created on first use.
func (s *Service) Analytics(ctx context.Context) (domain.Analytics, error) {
	if !s.d.AnalyticsEnabled {
		return domain.Analytics{Enabled: false}, nil
	}
	id, err := s.d.Installations.GetOrCreate(ctx, s.d.DB.Global(), s.d.Now())
	if err != nil {
		return domain.Analytics{}, fmt.Errorf("installation: %w", err)
	}
	collector, edition := domain.CollectorURL, s.d.Edition
	return domain.Analytics{Enabled: true, InstallID: &id, CollectorURL: &collector, Edition: &edition}, nil
}

// Balance is GET /balance for c. It returns nil (JSON null) when the
// deployment sells no balance. A source failure is ErrBalanceUnavailable,
// except an HTTP error the source raised itself, which passes through.
func (s *Service) Balance(ctx context.Context, c authn.Caller) (*domain.Balance, error) {
	if s.d.Balance == nil {
		return nil, nil
	}
	b, err := s.d.Balance.Balance(ctx, c)
	if err != nil {
		var httpErr *httpx.Error
		if errors.As(err, &httpErr) {
			return nil, err
		}
		s.d.Log.ErrorContext(ctx, "balance read failed", "workspace", c.Workspace.ID(), "error", err)
		return nil, fmt.Errorf("%w: %w", ErrBalanceUnavailable, err)
	}
	out := domain.Balance{Currency: string(b.Currency), Exhausted: b.Exhausted, ViewerIsPayer: b.ViewerIsPayer}
	if b.Amount != nil {
		out.Amount = text(b.Amount.String())
	}
	if b.SpendPerDay != nil {
		out.SpendPerDay = text(b.SpendPerDay.String())
	}
	if b.RunwayDays != nil {
		out.RunwayDays = text(b.RunwayDays.String())
	}
	return &out, nil
}

func text(s string) *string { return &s }
