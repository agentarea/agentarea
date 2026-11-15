package service

import (
	"context"
	"log/slog"
	"net/http"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/domain"
)

// Store is the wallet repository (store.Store).
type Store interface {
	WalletByAgent(ctx context.Context, s db.Session, agentID uuid.UUID) (api.Wallet, bool, error)
	CreateWallet(ctx context.Context, s db.Session, id, agentID uuid.UUID, createdBy string, n domain.New, now time.Time) (api.Wallet, error)
	UpdateWallet(ctx context.Context, s db.Session, id uuid.UUID, p domain.Patch, now time.Time) (api.Wallet, bool, error)
	DeleteWallet(ctx context.Context, s db.Session, id uuid.UUID) (bool, error)
	Exhausted(ctx context.Context, s db.Session, dailyStart, monthlyStart, heldSince time.Time) ([]api.Wallet, error)
	// LockWallet is WalletByAgent with the row locked until the transaction ends.
	LockWallet(ctx context.Context, s db.Session, agentID uuid.UUID) (api.Wallet, bool, error)
	InsertPayment(ctx context.Context, s db.Session, id, walletID uuid.UUID, agentID, status string, r api.Reservation, now time.Time) (api.Payment, error)
	SettledByKey(ctx context.Context, s db.Session, key string) (api.Payment, bool, error)
	PendingByKey(ctx context.Context, s db.Session, key string, heldSince time.Time) (api.Payment, bool, error)
	Sign(ctx context.Context, s db.Session, id uuid.UUID, signed http.Header) (api.Payment, bool, error)
	Settle(ctx context.Context, s db.Session, id uuid.UUID, status string, st api.Settlement, now time.Time) (api.Payment, bool, error)
	// The sums count settled payments, and pending reservations made since
	// heldSince when it is not nil.
	SumByExecution(ctx context.Context, s db.Session, agentID, executionID string, heldSince *time.Time) (money.Decimal, error)
	SumSince(ctx context.Context, s db.Session, agentID string, since, heldSince *time.Time) (money.Decimal, error)
	ListPayments(ctx context.Context, s db.Session, agentID string, f domain.PaymentFilter, limit, offset int32) ([]api.Payment, error)
	CountPayments(ctx context.Context, s db.Session, agentID string, f domain.PaymentFilter) (int, error)
}

// Agents resolves the agent a path names (agents module).
type Agents interface {
	// Resolve is resolve_agent_id: a UUID, else a slug, of an agent in ws;
	// false when the workspace has none.
	Resolve(ctx context.Context, ws scope.Workspace, idOrSlug string) (uuid.UUID, bool, error)
}

// Secrets is the workspace secret store a session reads and writes: the
// wallet keys live there and nowhere else.
type Secrets interface {
	Manager(s db.Session, userID string) secrets.Manager
}

// Deps are the service's ports.
type Deps struct {
	DB      db.Database
	Store   Store
	Agents  Agents
	Secrets Secrets
	Log     *slog.Logger
	// Now is the wall clock payment and wallet timestamps are written in; nil is time.Now.
	Now func() time.Time
}
