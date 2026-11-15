package service

import (
	"context"
	"log/slog"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/domain"
)

// Service is WalletService (agentarea_wallet/application/wallet_service.py)
// and what the payment path of a run calls (api.Wallets).
type Service struct {
	d Deps
}

var _ api.Wallets = (*Service)(nil)

// New builds the service.
func New(d Deps) *Service {
	if d.Now == nil {
		d.Now = time.Now
	}
	if d.Log == nil {
		d.Log = slog.New(slog.DiscardHandler)
	}
	return &Service{d: d}
}

func (s *Service) read(ctx context.Context, ws scope.Workspace, fn func(db.Session) error) error {
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return err
	}
	defer release()
	return fn(sess)
}

func (s *Service) write(ctx context.Context, ws scope.Workspace, fn func(db.Session) error) error {
	return s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error { return fn(sess) })
}

// ResolveAgent is resolve_agent_id; domain.ErrAgentNotFound when the
// workspace has no such agent.
func (s *Service) ResolveAgent(ctx context.Context, ws scope.Workspace, idOrSlug string) (uuid.UUID, error) {
	id, ok, err := s.d.Agents.Resolve(ctx, ws, idOrSlug)
	if err != nil {
		return uuid.Nil, err
	}
	if !ok {
		return uuid.Nil, domain.ErrAgentNotFound
	}
	return id, nil
}

// Credentials are the keys a create or update stores; a nil key is left out.
type Credentials struct {
	X402PrivateKey *string
	MPPTempoKey    *string
}

// Create is the input of create_wallet. X402Config and MPPConfig are the JSON
// objects to store, nil when the request gave none.
type Create struct {
	Type        string
	X402Config  []byte
	MPPConfig   []byte
	Credentials *Credentials
	Budget      money.Decimal
	Period      string
}

// Update is the input of update_wallet: a nil field is left as it is.
type Update struct {
	Type        *string
	X402Config  []byte
	MPPConfig   []byte
	Credentials *Credentials
	Budget      *money.Decimal
	Period      *string
	Status      *string
}

func plain(d *money.Decimal) *string {
	if d == nil {
		return nil
	}
	p := d.Plain()
	return &p
}

// credentialsJSON is json.dumps of the keys given, in the order Python's
// model_dump writes them, merged over what the secret holds already.
func credentialsJSON(existing wirejson.Object, c Credentials) ([]byte, error) {
	out := wirejson.Object{}
	out = append(out, existing...)
	if c.X402PrivateKey != nil {
		out.Set("x402_private_key", *c.X402PrivateKey)
	}
	if c.MPPTempoKey != nil {
		out.Set("mpp_tempo_key", *c.MPPTempoKey)
	}
	return wirejson.Marshal(out, wirejson.Dumps)
}

func has(raw []byte) bool { return len(raw) > 0 }

// Create makes the agent's wallet. The keys are written after the row, last
// in its transaction: a refused or failed insert stores no key, and a key
// written to a backend outside the transaction (Infisical) is deleted again
// when the transaction does not commit.
func (s *Service) Create(ctx context.Context, ws scope.Workspace, userID string, agentID uuid.UUID, in Create) (api.Wallet, error) {
	if err := domain.ValidateConfig(in.Type, has(in.X402Config), has(in.MPPConfig)); err != nil {
		return api.Wallet{}, err
	}
	n := domain.New{
		Type: in.Type, X402Config: in.X402Config, MPPConfig: in.MPPConfig,
		Budget: in.Budget.Plain(), Period: in.Period,
	}
	ref := string(api.CredentialsRef(agentID.String()))
	var raw []byte
	if in.Credentials != nil {
		var err error
		if raw, err = credentialsJSON(nil, *in.Credentials); err != nil {
			return api.Wallet{}, err
		}
		n.CredentialsRef = &ref
	}
	var out api.Wallet
	stored := false
	err := s.write(ctx, ws, func(sess db.Session) error {
		if _, ok, err := s.d.Store.WalletByAgent(ctx, sess, agentID); err != nil {
			return err
		} else if ok {
			return domain.ErrAlreadyExists
		}
		w, err := s.d.Store.CreateWallet(ctx, sess, uuid.New(), agentID, userID, n, s.d.Now())
		if err != nil {
			return err
		}
		if raw != nil {
			if err := s.d.Secrets.Manager(sess, userID).Set(ctx, ref, string(raw)); err != nil {
				return err
			}
			stored = true
			s.d.Log.InfoContext(ctx, "Stored wallet credentials", "agent_id", agentID.String())
		}
		out = w
		return nil
	})
	if err != nil {
		if stored {
			s.dropKey(ctx, ws, userID, agentID, ref)
		}
		return api.Wallet{}, err
	}
	s.d.Log.InfoContext(ctx, "Created wallet", "wallet_id", out.ID, "agent_id", agentID.String())
	return out, nil
}

// dropKey deletes the key a create wrote before its transaction failed.
func (s *Service) dropKey(ctx context.Context, ws scope.Workspace, userID string, agentID uuid.UUID, ref string) {
	bg := context.WithoutCancel(ctx)
	err := s.write(bg, ws, func(sess db.Session) error {
		_, err := s.d.Secrets.Manager(sess, userID).Delete(bg, ref)
		return err
	})
	if err != nil {
		s.d.Log.ErrorContext(ctx, "Failed to delete the credentials of a wallet that was not created", "agent_id", agentID.String(), "secret", ref, "error", err)
	}
}

// Get is get_wallet; api.ErrNotFound when the agent has none.
func (s *Service) Get(ctx context.Context, ws scope.Workspace, agentID uuid.UUID) (api.Wallet, error) {
	var w api.Wallet
	err := s.read(ctx, ws, func(sess db.Session) error {
		var err error
		w, err = s.wallet(ctx, sess, agentID)
		return err
	})
	return w, err
}

func (s *Service) wallet(ctx context.Context, sess db.Session, agentID uuid.UUID) (api.Wallet, error) {
	w, ok, err := s.d.Store.WalletByAgent(ctx, sess, agentID)
	if err != nil {
		return api.Wallet{}, err
	}
	if !ok {
		return api.Wallet{}, api.ErrNotFound
	}
	return w, nil
}

// existingCredentials is the JSON object the wallet's secret holds, empty
// when there is none or it is not an object. A secret that cannot be read is
// an error: merging over it would drop the key it holds.
func (s *Service) existingCredentials(ctx context.Context, m secrets.Manager, ref string) (wirejson.Object, error) {
	raw, err := m.Get(ctx, ref)
	if isNotFound(err) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if raw == "" {
		return nil, nil
	}
	v, err := wirejson.Unmarshal([]byte(raw))
	if err != nil {
		s.d.Log.WarnContext(ctx, "Wallet credentials secret is not valid JSON", "secret", ref)
		return nil, nil
	}
	o, _ := v.(wirejson.Object)
	return o, nil
}

// Update is update_wallet. Keys sent are merged into the stored ones: a
// request that sets one key keeps the other.
func (s *Service) Update(ctx context.Context, ws scope.Workspace, userID string, agentID uuid.UUID, in Update) (api.Wallet, error) {
	var out api.Wallet
	err := s.write(ctx, ws, func(sess db.Session) error {
		w, err := s.wallet(ctx, sess, agentID)
		if err != nil {
			return err
		}
		walletType := w.Type
		if in.Type != nil {
			walletType = *in.Type
		}
		hasX402, hasMPP := has(w.X402Config), has(w.MPPConfig)
		if in.X402Config != nil {
			hasX402 = true
		}
		if in.MPPConfig != nil {
			hasMPP = true
		}
		if err := domain.ValidateConfig(walletType, hasX402, hasMPP); err != nil {
			return err
		}
		p := domain.Patch{
			Type: in.Type, X402Config: in.X402Config, MPPConfig: in.MPPConfig,
			Budget: plain(in.Budget), Period: in.Period, Status: in.Status,
		}
		ref := string(api.CredentialsRef(agentID.String()))
		m := s.d.Secrets.Manager(sess, userID)
		var raw []byte
		if in.Credentials != nil {
			existing, err := s.existingCredentials(ctx, m, ref)
			if err != nil {
				return err
			}
			if raw, err = credentialsJSON(existing, *in.Credentials); err != nil {
				return err
			}
			p.CredentialsRef = &ref
		}
		u, ok, err := s.d.Store.UpdateWallet(ctx, sess, uuid.MustParse(w.ID), p, s.d.Now())
		if err != nil {
			return err
		}
		if !ok {
			return api.ErrNotFound
		}
		if raw != nil {
			if err := m.Set(ctx, ref, string(raw)); err != nil {
				return err
			}
			s.d.Log.InfoContext(ctx, "Updated wallet credentials", "agent_id", agentID.String())
		}
		out = u
		return nil
	})
	return out, err
}

// Delete is delete_wallet: the wallet row goes first, its payment records
// with it, then the keys secret, in one transaction. A secret that cannot be
// deleted fails the call and rolls the row back.
func (s *Service) Delete(ctx context.Context, ws scope.Workspace, userID string, agentID uuid.UUID) error {
	return s.write(ctx, ws, func(sess db.Session) error {
		w, err := s.wallet(ctx, sess, agentID)
		if err != nil {
			return err
		}
		if _, err := s.d.Store.DeleteWallet(ctx, sess, uuid.MustParse(w.ID)); err != nil {
			return err
		}
		if w.CredentialsRef != nil && *w.CredentialsRef != "" {
			if _, err := s.d.Secrets.Manager(sess, userID).Delete(ctx, string(*w.CredentialsRef)); err != nil {
				s.d.Log.ErrorContext(ctx, "Failed to delete wallet credentials secret", "agent_id", agentID.String(), "error", err)
				return err
			}
		}
		s.d.Log.InfoContext(ctx, "Deleted wallet", "wallet_id", w.ID, "agent_id", agentID.String())
		return nil
	})
}

// spent is the agent's settled spend of the wallet's current budget period:
// since midnight UTC or the first of the month, else all time. An
// execution-period wallet sums every execution, as get_total_spent_current_period does.
// held adds what the period's live pending reservations hold.
func (s *Service) spent(ctx context.Context, sess db.Session, w api.Wallet, held bool) (money.Decimal, error) {
	var since, heldSince *time.Time
	if t, ok := domain.PeriodStart(w.Period, s.d.Now()); ok {
		since = &t
	}
	if held {
		h := s.heldSince()
		heldSince = &h
	}
	return s.d.Store.SumSince(ctx, sess, w.AgentID, since, heldSince)
}

// heldSince is when the oldest reservation still holding budget was made.
func (s *Service) heldSince() time.Time { return s.d.Now().Add(-api.ReservationHold) }

// atLeastZero is max(ZERO, d): zero keeps the plain "0".
func atLeastZero(d money.Decimal) money.Decimal {
	if d.Sign() > 0 {
		return d
	}
	return money.Zero()
}

// Balance is the balance route's state for the agent's wallet.
func (s *Service) Balance(ctx context.Context, ws scope.Workspace, agentID string) (api.Balance, error) {
	id, err := uuid.Parse(agentID)
	if err != nil {
		return api.Balance{}, api.ErrNotFound
	}
	var b api.Balance
	err = s.read(ctx, ws, func(sess db.Session) error {
		w, err := s.wallet(ctx, sess, id)
		if err != nil {
			return err
		}
		spent, err := s.spent(ctx, sess, w, false)
		if err != nil {
			return err
		}
		committed, err := s.spent(ctx, sess, w, true)
		if err != nil {
			return err
		}
		b = api.Balance{Budget: w.Budget, Period: w.Period, Spent: spent, Remaining: atLeastZero(w.Budget.Sub(committed))}
		return nil
	})
	return b, err
}

// PaymentPage is a page of an agent's payments and how many match the filter.
type PaymentPage struct {
	Items []api.Payment
	Total int
}

// Payments is get_payment_history: newest first, Total counting what the
// filter matches. An agent without a wallet has an empty page.
func (s *Service) Payments(ctx context.Context, ws scope.Workspace, agentID uuid.UUID, f domain.PaymentFilter, limit, offset int32) (PaymentPage, error) {
	var p PaymentPage
	err := s.read(ctx, ws, func(sess db.Session) error {
		items, err := s.d.Store.ListPayments(ctx, sess, agentID.String(), f, limit, offset)
		if err != nil {
			return err
		}
		total, err := s.d.Store.CountPayments(ctx, sess, agentID.String(), f)
		p = PaymentPage{Items: items, Total: total}
		return err
	})
	return p, err
}
