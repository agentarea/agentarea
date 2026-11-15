package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/domain"
)

type paymentRow struct {
	ID               uuid.UUID
	WalletID         uuid.UUID
	AgentID          string
	ExecutionID      string
	Protocol         string
	AmountUsd        string
	Recipient        string
	TxHash           pgtype.Text
	ToolName         string
	ToolCallID       string
	IdempotencyKey   string
	Status           string
	ErrorMessage     pgtype.Text
	ProtocolMetadata string
	CreatedAt        pgtype.Timestamp
}

func payment(r paymentRow) (api.Payment, error) {
	amount, err := decimal(r.AmountUsd)
	if err != nil {
		return api.Payment{}, err
	}
	return api.Payment{
		ID: r.ID.String(), WalletID: r.WalletID.String(), AgentID: r.AgentID, ExecutionID: r.ExecutionID,
		Protocol: r.Protocol, Amount: amount, Recipient: r.Recipient, TxHash: fromText(r.TxHash),
		ToolName: r.ToolName, ToolCallID: r.ToolCallID, IdempotencyKey: r.IdempotencyKey, Status: r.Status,
		ErrorMessage: fromText(r.ErrorMessage), ProtocolMetadata: rawJSON(r.ProtocolMetadata), CreatedAt: r.CreatedAt.Time,
	}, nil
}

// InsertPayment writes a payment record on the wallet with status, for the
// agent's canonical id; created_by is r.UserID. The second completed record
// under one idempotency key in the workspace writes nothing and is
// api.ErrAlreadySettled.
func (Store) InsertPayment(ctx context.Context, s db.Session, id, walletID uuid.UUID, agentID, status string, r api.Reservation, now time.Time) (api.Payment, error) {
	row, err := New(s.Q()).InsertPayment(ctx, InsertPaymentParams{
		ID: id, Now: naive(now), WorkspaceID: s.Workspace().ID(), CreatedBy: r.UserID, WalletID: walletID,
		AgentID: agentID, ExecutionID: r.ExecutionID, Protocol: r.Protocol, AmountUsd: r.Amount.Plain(),
		Recipient: r.Recipient, ToolName: r.ToolName, ToolCallID: r.ToolCallID,
		IdempotencyKey: r.IdempotencyKey, Status: status, ProtocolMetadata: jsonText(r.ProtocolMetadata),
	})
	if errors.Is(err, pgx.ErrNoRows) {
		return api.Payment{}, api.ErrAlreadySettled
	}
	if err != nil {
		return api.Payment{}, err
	}
	return payment(paymentRow(row))
}

// SettledByKey is the completed payment under the idempotency key.
func (Store) SettledByKey(ctx context.Context, s db.Session, key string) (api.Payment, bool, error) {
	r, err := New(s.Q()).SettledPaymentByKey(ctx, SettledPaymentByKeyParams{WorkspaceID: s.Workspace().ID(), IdempotencyKey: key})
	if errors.Is(err, pgx.ErrNoRows) {
		return api.Payment{}, false, nil
	}
	if err != nil {
		return api.Payment{}, false, err
	}
	p, err := payment(paymentRow(r))
	return p, err == nil, err
}

// PendingByKey is the reservation under the idempotency key still holding:
// pending and made since heldSince, or pending and signed; a signed one first.
func (Store) PendingByKey(ctx context.Context, s db.Session, key string, heldSince time.Time) (api.Payment, bool, error) {
	r, err := New(s.Q()).PendingPaymentByKey(ctx, PendingPaymentByKeyParams{WorkspaceID: s.Workspace().ID(), IdempotencyKey: key, HeldSince: naive(heldSince)})
	if errors.Is(err, pgx.ErrNoRows) {
		return api.Payment{}, false, nil
	}
	if err != nil {
		return api.Payment{}, false, err
	}
	p, err := signedPayment(LockPendingPaymentRow(r))
	return p, err == nil, err
}

// Sign stores signed on the pending payment id unless it holds one already,
// and returns the payment as stored; false when no pending payment has the id.
func (Store) Sign(ctx context.Context, s db.Session, id uuid.UUID, signed http.Header) (api.Payment, bool, error) {
	q := New(s.Q())
	r, err := q.LockPendingPayment(ctx, LockPendingPaymentParams{WorkspaceID: s.Workspace().ID(), ID: id})
	if errors.Is(err, pgx.ErrNoRows) {
		return api.Payment{}, false, nil
	}
	if err != nil {
		return api.Payment{}, false, err
	}
	if r.SignedHeaders == "" {
		raw, err := json.Marshal(signed)
		if err != nil {
			return api.Payment{}, false, err
		}
		if err := q.SetPaymentSigned(ctx, SetPaymentSignedParams{SignedHeaders: string(raw), WorkspaceID: s.Workspace().ID(), ID: id}); err != nil {
			return api.Payment{}, false, err
		}
		r.SignedHeaders = string(raw)
	}
	p, err := signedPayment(r)
	return p, err == nil, err
}

func signedPayment(r LockPendingPaymentRow) (api.Payment, error) {
	p, err := payment(paymentRow{ID: r.ID, WalletID: r.WalletID, AgentID: r.AgentID, ExecutionID: r.ExecutionID, Protocol: r.Protocol,
		AmountUsd: r.AmountUsd, Recipient: r.Recipient, TxHash: r.TxHash, ToolName: r.ToolName, ToolCallID: r.ToolCallID,
		IdempotencyKey: r.IdempotencyKey, Status: r.Status, ErrorMessage: r.ErrorMessage, ProtocolMetadata: r.ProtocolMetadata, CreatedAt: r.CreatedAt})
	if err != nil || r.SignedHeaders == "" {
		return p, err
	}
	if err := json.Unmarshal([]byte(r.SignedHeaders), &p.Signed); err != nil {
		return api.Payment{}, fmt.Errorf("payment %s signed headers: %w", r.ID, err)
	}
	return p, nil
}

// Settle ends the pending reservation id with status. It reports false when
// the workspace has no pending payment of that id; completing one whose key
// settled meanwhile is api.ErrAlreadySettled.
func (Store) Settle(ctx context.Context, s db.Session, id uuid.UUID, status string, st api.Settlement, now time.Time) (api.Payment, bool, error) {
	r, err := New(s.Q()).SettlePayment(ctx, SettlePaymentParams{
		Status: status, TxHash: text(st.TxHash), ErrorMessage: text(st.ErrorMessage), ProtocolMetadata: jsonText(st.ProtocolMetadata),
		Now: naive(now), WorkspaceID: s.Workspace().ID(), ID: id,
	})
	if errors.Is(err, pgx.ErrNoRows) {
		return api.Payment{}, false, nil
	}
	if isUnique(err) {
		return api.Payment{}, false, api.ErrAlreadySettled
	}
	if err != nil {
		return api.Payment{}, false, err
	}
	p, err := payment(paymentRow(r))
	return p, err == nil, err
}

// SumByExecution is the agent's settled spend in one execution, plus the
// pending reservations made since heldSince when it is set.
func (Store) SumByExecution(ctx context.Context, s db.Session, agentID, executionID string, heldSince *time.Time) (money.Decimal, error) {
	t, err := New(s.Q()).SumPaymentsByExecution(ctx, SumPaymentsByExecutionParams{
		WorkspaceID: s.Workspace().ID(), AgentID: agentID, ExecutionID: executionID, HeldSince: optNaive(heldSince),
	})
	if err != nil {
		return money.Decimal{}, err
	}
	return decimal(t)
}

// SumSince is the agent's settled spend since the instant, or all time when
// since is nil, plus the pending reservations made since heldSince when it is set.
func (Store) SumSince(ctx context.Context, s db.Session, agentID string, since, heldSince *time.Time) (money.Decimal, error) {
	t, err := New(s.Q()).SumPaymentsSince(ctx, SumPaymentsSinceParams{
		WorkspaceID: s.Workspace().ID(), AgentID: agentID, Since: optNaive(since), HeldSince: optNaive(heldSince),
	})
	if err != nil {
		return money.Decimal{}, err
	}
	return decimal(t)
}

// ListPayments is a page of the agent's payments, newest first.
func (Store) ListPayments(ctx context.Context, s db.Session, agentID string, f domain.PaymentFilter, limit, offset int32) ([]api.Payment, error) {
	rows, err := New(s.Q()).ListPayments(ctx, ListPaymentsParams{
		WorkspaceID: s.Workspace().ID(), AgentID: agentID, Protocol: text(f.Protocol), Status: text(f.Status),
		FromDate: optNaive(f.From), ToDate: optNaive(f.To), Lim: limit, Off: offset,
	})
	if err != nil {
		return nil, err
	}
	out := make([]api.Payment, len(rows))
	for i, r := range rows {
		if out[i], err = payment(paymentRow(r)); err != nil {
			return nil, err
		}
	}
	return out, nil
}

// CountPayments is how many payments of the agent match the filter.
func (Store) CountPayments(ctx context.Context, s db.Session, agentID string, f domain.PaymentFilter) (int, error) {
	n, err := New(s.Q()).CountPayments(ctx, CountPaymentsParams{
		WorkspaceID: s.Workspace().ID(), AgentID: agentID, Protocol: text(f.Protocol), Status: text(f.Status),
		FromDate: optNaive(f.From), ToDate: optNaive(f.To),
	})
	return int(n), err
}
