package service

import (
	"context"
	"errors"
	"fmt"
	"net/http"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/domain"
)

func (s *Service) walletOf(ctx context.Context, sess db.Session, agentID string) (api.Wallet, error) {
	id, err := uuid.Parse(agentID)
	if err != nil {
		return api.Wallet{}, api.ErrNotFound
	}
	return s.wallet(ctx, sess, id)
}

// remaining is get_service_budget_remaining: the budget less the settled
// spend and pending reservations of the execution (execution period) or of
// the current day or month, never below zero.
func (s *Service) remaining(ctx context.Context, sess db.Session, w api.Wallet, executionID string) (money.Decimal, error) {
	var spent money.Decimal
	var err error
	if w.Period == api.PeriodExecution {
		h := s.heldSince()
		spent, err = s.d.Store.SumByExecution(ctx, sess, w.AgentID, executionID, &h)
	} else {
		spent, err = s.spent(ctx, sess, w, true)
	}
	if err != nil {
		return money.Decimal{}, err
	}
	return atLeastZero(w.Budget.Sub(spent)), nil
}

// Active implements api.Wallets.
func (s *Service) Active(ctx context.Context, ws scope.Workspace, agentID, executionID string) (api.Payable, bool, error) {
	var p api.Payable
	var found bool
	err := s.read(ctx, ws, func(sess db.Session) error {
		w, err := s.walletOf(ctx, sess, agentID)
		if errors.Is(err, api.ErrNotFound) {
			return nil
		}
		if err != nil {
			return err
		}
		if w.Status != api.StatusActive {
			return nil
		}
		left, err := s.remaining(ctx, sess, w, executionID)
		if err != nil {
			return err
		}
		p, found = api.Payable{Wallet: w, ExecutionID: executionID, Remaining: left}, true
		return nil
	})
	return p, found, err
}

// Credentials implements api.Wallets. The keys are read from the secret store
// at this call and returned to the caller only.
func (s *Service) Credentials(ctx context.Context, ws scope.Workspace, w api.Wallet) (api.Credentials, error) {
	if w.CredentialsRef == nil || *w.CredentialsRef == "" {
		return api.Credentials{}, nil
	}
	var c api.Credentials
	err := s.read(ctx, ws, func(sess db.Session) error {
		raw, err := s.d.Secrets.Manager(sess, "").Get(ctx, string(*w.CredentialsRef))
		if err != nil {
			if isNotFound(err) {
				return nil
			}
			return err
		}
		if raw == "" {
			return nil
		}
		v, err := wirejson.Unmarshal([]byte(raw))
		o, isObject := v.(wirejson.Object)
		if err != nil || !isObject {
			s.d.Log.WarnContext(ctx, "Wallet credentials secret is not a JSON object", "agent_id", w.AgentID)
			return nil
		}
		str := func(key string) string {
			x, _ := o.Get(key)
			s, _ := x.(string)
			return s
		}
		c = api.NewCredentials(str("x402_private_key"), str("mpp_tempo_key"))
		return nil
	})
	return c, err
}

// FindSettled implements api.Wallets.
func (s *Service) FindSettled(ctx context.Context, ws scope.Workspace, key string) (api.Payment, bool, error) {
	var p api.Payment
	var ok bool
	err := s.read(ctx, ws, func(sess db.Session) error {
		var err error
		p, ok, err = s.d.Store.SettledByKey(ctx, sess, key)
		return err
	})
	return p, ok, err
}

// checkReservation refuses what payment_records cannot hold and rounds the
// amount to the column's six places, so no later step expands an exponent
// the caller chose (1E-2000000000 is two billion digits in plain form).
func checkReservation(r api.Reservation) (api.Reservation, error) {
	switch {
	case r.Protocol != api.ProtocolX402 && r.Protocol != api.ProtocolMPP:
		return r, fmt.Errorf("wallet: payment protocol %q is not x402 or mpp", r.Protocol)
	case r.Amount.Sign() < 0 || api.Adjusted(r.Amount) >= 12:
		return r, fmt.Errorf("wallet: payment amount %s is outside numeric(18, 6)", r.Amount)
	case r.IdempotencyKey == "":
		return r, fmt.Errorf("wallet: a payment needs an idempotency key")
	}
	r.Amount = api.Quantize6(r.Amount)
	if api.Adjusted(r.Amount) >= 12 {
		return r, fmt.Errorf("wallet: payment amount %s is outside numeric(18, 6)", r.Amount)
	}
	return r, nil
}

// Reserve implements api.Wallets. The wallet row stays locked from the
// budget check to the insert, so reservations of one wallet are serial.
func (s *Service) Reserve(ctx context.Context, ws scope.Workspace, in api.Reservation) (api.Payment, error) {
	r, err := checkReservation(in)
	if err != nil {
		return api.Payment{}, err
	}
	agentID, err := uuid.Parse(r.AgentID)
	if err != nil {
		return api.Payment{}, api.ErrNotFound
	}
	var out api.Payment
	err = s.write(ctx, ws, func(sess db.Session) error {
		w, ok, err := s.d.Store.LockWallet(ctx, sess, agentID)
		if err != nil {
			return err
		}
		if !ok {
			return api.ErrNotFound
		}
		if w.Status != api.StatusActive {
			return api.ErrWalletDisabled
		}
		if _, ok, err := s.d.Store.SettledByKey(ctx, sess, r.IdempotencyKey); err != nil {
			return err
		} else if ok {
			return api.ErrAlreadySettled
		}
		if p, ok, err := s.d.Store.PendingByKey(ctx, sess, r.IdempotencyKey, s.heldSince()); err != nil {
			return err
		} else if ok && p.WalletID == w.ID {
			out = p
			return nil
		}
		left, err := s.remaining(ctx, sess, w, r.ExecutionID)
		if err != nil {
			return err
		}
		if r.Amount.Cmp(left) > 0 {
			return &api.BudgetError{Amount: r.Amount, Remaining: left}
		}
		out, err = s.d.Store.InsertPayment(ctx, sess, uuid.New(), uuid.MustParse(w.ID), w.AgentID, api.PaymentPending, r, s.d.Now())
		return err
	})
	if err != nil {
		return api.Payment{}, err
	}
	s.d.Log.InfoContext(ctx, "Reserved payment", "payment_id", out.ID, "agent_id", out.AgentID, "execution_id", out.ExecutionID, "amount", out.Amount.String())
	return out, nil
}

// Sign implements api.Wallets.
func (s *Service) Sign(ctx context.Context, ws scope.Workspace, paymentID string, signed http.Header) (api.Payment, error) {
	id, err := uuid.Parse(paymentID)
	if err != nil {
		return api.Payment{}, api.ErrNotReserved
	}
	if len(signed) == 0 {
		return api.Payment{}, fmt.Errorf("wallet: payment %s has no signed payment to store", paymentID)
	}
	var out api.Payment
	err = s.write(ctx, ws, func(sess db.Session) error {
		p, ok, err := s.d.Store.Sign(ctx, sess, id, signed)
		if err != nil {
			return err
		}
		if !ok {
			return api.ErrNotReserved
		}
		out = p
		return nil
	})
	return out, err
}

// Complete implements api.Wallets.
func (s *Service) Complete(ctx context.Context, ws scope.Workspace, paymentID string, st api.Settlement) (api.Payment, error) {
	return s.settle(ctx, ws, paymentID, api.PaymentCompleted, st)
}

// Fail implements api.Wallets.
func (s *Service) Fail(ctx context.Context, ws scope.Workspace, paymentID string, st api.Settlement) (api.Payment, error) {
	return s.settle(ctx, ws, paymentID, api.PaymentFailed, st)
}

func (s *Service) settle(ctx context.Context, ws scope.Workspace, paymentID, status string, st api.Settlement) (api.Payment, error) {
	id, err := uuid.Parse(paymentID)
	if err != nil {
		return api.Payment{}, api.ErrNotReserved
	}
	var out api.Payment
	err = s.write(ctx, ws, func(sess db.Session) error {
		p, ok, err := s.d.Store.Settle(ctx, sess, id, status, st, s.d.Now())
		if err != nil {
			return err
		}
		if !ok {
			return api.ErrNotReserved
		}
		out = p
		return nil
	})
	if err != nil {
		return api.Payment{}, err
	}
	s.d.Log.InfoContext(ctx, "Settled payment", "payment_id", out.ID, "status", out.Status, "agent_id", out.AgentID, "amount", out.Amount.String())
	return out, nil
}

// Exhausted implements api.Wallets.
func (s *Service) Exhausted(ctx context.Context, ws scope.Workspace) ([]api.Exhausted, error) {
	now := s.d.Now()
	daily, _ := domain.PeriodStart(api.PeriodDaily, now)
	monthly, _ := domain.PeriodStart(api.PeriodMonthly, now)
	var out []api.Exhausted
	err := s.read(ctx, ws, func(sess db.Session) error {
		ws, err := s.d.Store.Exhausted(ctx, sess, daily, monthly, s.heldSince())
		if err != nil {
			return err
		}
		out = make([]api.Exhausted, len(ws))
		for i, w := range ws {
			out[i] = api.Exhausted{AgentID: w.AgentID, Budget: w.Budget, Period: w.Period}
		}
		return nil
	})
	return out, err
}

func isNotFound(err error) bool { return errors.Is(err, secrets.ErrNotFound) }
