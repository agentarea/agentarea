package store

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/domain"
)

//go:generate sqlc generate

// Store reads and writes agent_wallets and payment_records inside the
// session's workspace.
type Store struct{}

const uniqueViolation = "23505"

func text(p *string) pgtype.Text {
	if p == nil {
		return pgtype.Text{}
	}
	return pgtype.Text{String: *p, Valid: true}
}

func fromText(t pgtype.Text) *string {
	if !t.Valid {
		return nil
	}
	s := t.String
	return &s
}

func jsonText(raw []byte) pgtype.Text {
	if len(raw) == 0 {
		return pgtype.Text{}
	}
	return pgtype.Text{String: string(raw), Valid: true}
}

// rawJSON is a stored json column read back as text: SQL NULL arrives as the
// JSON text "null", and SQLAlchemy wrote JSON null for a missing value, so
// both mean none.
func rawJSON(s string) json.RawMessage {
	if s == "" || s == "null" {
		return nil
	}
	return json.RawMessage(s)
}

func naive(t time.Time) pgtype.Timestamp {
	return pgtype.Timestamp{Time: t.UTC().Truncate(time.Microsecond), Valid: true}
}

func optNaive(t *time.Time) pgtype.Timestamp {
	if t == nil {
		return pgtype.Timestamp{}
	}
	return naive(*t)
}

func decimal(s string) (money.Decimal, error) { return money.Parse(s) }

func isUnique(err error) bool {
	var pg *pgconn.PgError
	return errors.As(err, &pg) && pg.Code == uniqueViolation
}

type walletRow struct {
	ID                  uuid.UUID
	WorkspaceID         string
	CreatedBy           string
	AgentID             uuid.UUID
	WalletType          string
	X402Json            string
	MppJson             string
	CredentialsSecretID pgtype.Text
	ServiceBudgetUsd    string
	ServiceBudgetPeriod string
	Status              string
	CreatedAt           pgtype.Timestamp
	UpdatedAt           pgtype.Timestamp
}

func wallet(r walletRow) (api.Wallet, error) {
	budget, err := decimal(r.ServiceBudgetUsd)
	if err != nil {
		return api.Wallet{}, err
	}
	w := api.Wallet{
		ID: r.ID.String(), AgentID: r.AgentID.String(), WorkspaceID: r.WorkspaceID, CreatedBy: r.CreatedBy,
		Type: r.WalletType, X402Config: rawJSON(r.X402Json), MPPConfig: rawJSON(r.MppJson),
		Budget: budget, Period: r.ServiceBudgetPeriod, Status: r.Status,
		CreatedAt: r.CreatedAt.Time, UpdatedAt: r.UpdatedAt.Time,
	}
	if r.CredentialsSecretID.Valid {
		ref := secrets.Ref(r.CredentialsSecretID.String)
		w.CredentialsRef = &ref
	}
	return w, nil
}

// WalletByAgent is the agent's wallet, false when it has none.
func (Store) WalletByAgent(ctx context.Context, s db.Session, agentID uuid.UUID) (api.Wallet, bool, error) {
	r, err := New(s.Q()).WalletByAgent(ctx, WalletByAgentParams{WorkspaceID: s.Workspace().ID(), AgentID: agentID})
	if errors.Is(err, pgx.ErrNoRows) {
		return api.Wallet{}, false, nil
	}
	if err != nil {
		return api.Wallet{}, false, err
	}
	w, err := wallet(walletRow(r))
	return w, err == nil, err
}

// LockWallet is WalletByAgent holding the row's lock until the session's
// transaction ends.
func (Store) LockWallet(ctx context.Context, s db.Session, agentID uuid.UUID) (api.Wallet, bool, error) {
	r, err := New(s.Q()).LockWalletByAgent(ctx, LockWalletByAgentParams{WorkspaceID: s.Workspace().ID(), AgentID: agentID})
	if errors.Is(err, pgx.ErrNoRows) {
		return api.Wallet{}, false, nil
	}
	if err != nil {
		return api.Wallet{}, false, err
	}
	w, err := wallet(walletRow(r))
	return w, err == nil, err
}

// CreateWallet inserts an active wallet; the agent's existing one is
// domain.ErrAlreadyExists.
func (Store) CreateWallet(ctx context.Context, s db.Session, id, agentID uuid.UUID, createdBy string, n domain.New, now time.Time) (api.Wallet, error) {
	r, err := New(s.Q()).CreateWallet(ctx, CreateWalletParams{
		ID: id, Now: naive(now), WorkspaceID: s.Workspace().ID(), CreatedBy: createdBy, AgentID: agentID,
		WalletType: n.Type, X402Config: jsonText(n.X402Config), MppConfig: jsonText(n.MPPConfig),
		CredentialsSecretID: text(n.CredentialsRef), ServiceBudgetUsd: n.Budget, ServiceBudgetPeriod: n.Period,
	})
	if isUnique(err) {
		return api.Wallet{}, domain.ErrAlreadyExists
	}
	if err != nil {
		return api.Wallet{}, err
	}
	return wallet(walletRow(r))
}

// UpdateWallet writes the fields p sets; updated_at moves only when a value
// changes. It reports false when the workspace has no such wallet.
func (Store) UpdateWallet(ctx context.Context, s db.Session, id uuid.UUID, p domain.Patch, now time.Time) (api.Wallet, bool, error) {
	arg := UpdateWalletParams{
		SetType: p.Type != nil, SetX402: p.X402Config != nil, X402Config: jsonText(p.X402Config),
		SetMpp: p.MPPConfig != nil, MppConfig: jsonText(p.MPPConfig),
		SetCredentials: p.CredentialsRef != nil, CredentialsSecretID: text(p.CredentialsRef),
		SetBudget: p.Budget != nil, SetPeriod: p.Period != nil, SetStatus: p.Status != nil,
		Now: naive(now), WorkspaceID: s.Workspace().ID(), ID: id,
	}
	if p.Type != nil {
		arg.WalletType = *p.Type
	}
	if p.Budget != nil {
		arg.ServiceBudgetUsd = *p.Budget
	}
	if p.Period != nil {
		arg.ServiceBudgetPeriod = *p.Period
	}
	if p.Status != nil {
		arg.Status = *p.Status
	}
	r, err := New(s.Q()).UpdateWallet(ctx, arg)
	if errors.Is(err, pgx.ErrNoRows) {
		return api.Wallet{}, false, nil
	}
	if err != nil {
		return api.Wallet{}, false, err
	}
	w, err := wallet(walletRow(r))
	return w, err == nil, err
}

// DeleteWallet removes the wallet; its payment records go with it (FK
// cascade). It reports false when there was none.
func (Store) DeleteWallet(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	n, err := New(s.Q()).DeleteWallet(ctx, DeleteWalletParams{WorkspaceID: s.Workspace().ID(), ID: id})
	return n > 0, err
}

// Exhausted lists the active daily and monthly wallets whose settled spend
// and pending reservations made since heldSince, counted from the period
// start, reached the budget.
func (Store) Exhausted(ctx context.Context, s db.Session, dailyStart, monthlyStart, heldSince time.Time) ([]api.Wallet, error) {
	rows, err := New(s.Q()).ExhaustedWallets(ctx, ExhaustedWalletsParams{
		WorkspaceID: s.Workspace().ID(), DailyStart: naive(dailyStart), MonthlyStart: naive(monthlyStart), HeldSince: naive(heldSince),
	})
	if err != nil {
		return nil, err
	}
	out := make([]api.Wallet, len(rows))
	for i, r := range rows {
		if out[i], err = wallet(walletRow(r)); err != nil {
			return nil, err
		}
	}
	return out, nil
}
