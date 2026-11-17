package service

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/wallet/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/wallet/domain"
)

type world struct {
	wallets  map[uuid.UUID]api.Wallet
	payments []api.Payment
	secrets  map[string]string
	failSet  error
	failDel  error
	failMake error
	failGet  error
	// external keeps secrets out of the transaction, as Infisical does.
	external   bool
	failCommit error
	failUpdate error
	failDrop   error
}

func (w *world) clone() world {
	c := world{wallets: map[uuid.UUID]api.Wallet{}, payments: append([]api.Payment(nil), w.payments...), secrets: map[string]string{}}
	for k, v := range w.wallets {
		c.wallets[k] = v
	}
	for k, v := range w.secrets {
		c.secrets[k] = v
	}
	return c
}

type fakeDB struct {
	db.Database
	w *world
}

func (fakeDB) Read(_ context.Context, ws scope.Workspace) (db.Session, func(), error) {
	return db.NewSession(ws, nil), func() {}, nil
}

func (f fakeDB) Write(ctx context.Context, ws scope.Workspace, fn func(context.Context, db.Session) error) error {
	before := f.w.clone()
	err := fn(ctx, db.NewTxSession(ws, nil))
	if err == nil && f.w.failCommit != nil {
		err = f.w.failCommit
		f.w.failCommit = nil
	}
	if err != nil {
		after := *f.w
		*f.w = before
		f.w.failSet, f.w.failDel, f.w.failMake, f.w.failGet = after.failSet, after.failDel, after.failMake, after.failGet
		f.w.external, f.w.failUpdate, f.w.failDrop = after.external, after.failUpdate, after.failDrop
		if after.external {
			f.w.secrets = after.secrets
		}
		return err
	}
	return nil
}

type fakeSecrets struct{ w *world }

func (f fakeSecrets) Manager(db.Session, string) secrets.Manager { return fakeManager(f) }

type fakeManager struct{ w *world }

func (m fakeManager) Get(_ context.Context, name string) (string, error) {
	if m.w.failGet != nil {
		return "", m.w.failGet
	}
	v, ok := m.w.secrets[name]
	if !ok {
		return "", secrets.ErrNotFound
	}
	return v, nil
}
func (m fakeManager) Set(_ context.Context, name, value string) error {
	if m.w.failSet != nil {
		return m.w.failSet
	}
	m.w.secrets[name] = value
	return nil
}
func (m fakeManager) Delete(_ context.Context, name string) (bool, error) {
	if m.w.failDel != nil {
		return false, m.w.failDel
	}
	_, ok := m.w.secrets[name]
	delete(m.w.secrets, name)
	return ok, nil
}
func (m fakeManager) Has(_ context.Context, name string) (bool, error) {
	_, ok := m.w.secrets[name]
	return ok, nil
}
func (fakeManager) ExternalRef(string) (string, bool) { return "", false }

type fakeStore struct{ w *world }

func (f fakeStore) WalletByAgent(_ context.Context, _ db.Session, agentID uuid.UUID) (api.Wallet, bool, error) {
	for _, w := range f.w.wallets {
		if w.AgentID == agentID.String() {
			return w, true, nil
		}
	}
	return api.Wallet{}, false, nil
}

func (f fakeStore) CreateWallet(_ context.Context, _ db.Session, id, agentID uuid.UUID, by string, n domain.New, now time.Time) (api.Wallet, error) {
	if f.w.failMake != nil {
		return api.Wallet{}, f.w.failMake
	}
	w := api.Wallet{
		ID: id.String(), AgentID: agentID.String(), CreatedBy: by, Type: n.Type, X402Config: n.X402Config, MPPConfig: n.MPPConfig,
		Budget: money.MustParse(n.Budget), Period: n.Period, Status: api.StatusActive, CreatedAt: now, UpdatedAt: now,
	}
	if n.CredentialsRef != nil {
		r := secrets.Ref(*n.CredentialsRef)
		w.CredentialsRef = &r
	}
	f.w.wallets[id] = w
	return w, nil
}

func (f fakeStore) UpdateWallet(_ context.Context, _ db.Session, id uuid.UUID, p domain.Patch, now time.Time) (api.Wallet, bool, error) {
	if f.w.failUpdate != nil {
		return api.Wallet{}, false, f.w.failUpdate
	}
	w, ok := f.w.wallets[id]
	if !ok {
		return api.Wallet{}, false, nil
	}
	if p.Type != nil {
		w.Type = *p.Type
	}
	if p.X402Config != nil {
		w.X402Config = p.X402Config
	}
	if p.MPPConfig != nil {
		w.MPPConfig = p.MPPConfig
	}
	if p.CredentialsRef != nil {
		r := secrets.Ref(*p.CredentialsRef)
		w.CredentialsRef = &r
	}
	if p.Budget != nil {
		w.Budget = money.MustParse(*p.Budget)
	}
	if p.Period != nil {
		w.Period = *p.Period
	}
	if p.Status != nil {
		w.Status = *p.Status
	}
	w.UpdatedAt = now
	f.w.wallets[id] = w
	return w, true, nil
}

func (f fakeStore) DeleteWallet(_ context.Context, _ db.Session, id uuid.UUID) (bool, error) {
	if f.w.failDrop != nil {
		return false, f.w.failDrop
	}
	_, ok := f.w.wallets[id]
	delete(f.w.wallets, id)
	return ok, nil
}

func (f fakeStore) Exhausted(context.Context, db.Session, time.Time, time.Time, time.Time) ([]api.Wallet, error) {
	return nil, nil
}

func (f fakeStore) LockWallet(ctx context.Context, s db.Session, agentID uuid.UUID) (api.Wallet, bool, error) {
	return f.WalletByAgent(ctx, s, agentID)
}

func (f fakeStore) InsertPayment(_ context.Context, _ db.Session, id, walletID uuid.UUID, agentID, status string, r api.Reservation, now time.Time) (api.Payment, error) {
	if status == api.PaymentCompleted {
		for _, p := range f.w.payments {
			if p.Status == api.PaymentCompleted && p.IdempotencyKey == r.IdempotencyKey {
				return api.Payment{}, api.ErrAlreadySettled
			}
		}
	}
	p := api.Payment{
		ID: id.String(), WalletID: walletID.String(), AgentID: agentID, ExecutionID: r.ExecutionID, Protocol: r.Protocol,
		Amount: r.Amount, IdempotencyKey: r.IdempotencyKey, Status: status, CreatedAt: now,
	}
	f.w.payments = append(f.w.payments, p)
	return p, nil
}

func (f fakeStore) byKey(key, status string) (api.Payment, bool, error) {
	for _, p := range f.w.payments {
		if p.Status == status && p.IdempotencyKey == key {
			return p, true, nil
		}
	}
	return api.Payment{}, false, nil
}

func (f fakeStore) SettledByKey(_ context.Context, _ db.Session, key string) (api.Payment, bool, error) {
	return f.byKey(key, api.PaymentCompleted)
}

func (f fakeStore) PendingByKey(_ context.Context, _ db.Session, key string, heldSince time.Time) (api.Payment, bool, error) {
	for _, p := range f.w.payments {
		if p.Status == api.PaymentPending && p.IdempotencyKey == key && (!p.CreatedAt.Before(heldSince) || p.Signed != nil) {
			return p, true, nil
		}
	}
	return api.Payment{}, false, nil
}

func (f fakeStore) Sign(_ context.Context, _ db.Session, id uuid.UUID, signed http.Header) (api.Payment, bool, error) {
	for i, p := range f.w.payments {
		if p.ID != id.String() || p.Status != api.PaymentPending {
			continue
		}
		if p.Signed == nil {
			f.w.payments[i].Signed = signed
		}
		return f.w.payments[i], true, nil
	}
	return api.Payment{}, false, nil
}

func (f fakeStore) Settle(_ context.Context, _ db.Session, id uuid.UUID, status string, st api.Settlement, _ time.Time) (api.Payment, bool, error) {
	for i, p := range f.w.payments {
		if p.ID != id.String() || p.Status != api.PaymentPending {
			continue
		}
		if status == api.PaymentCompleted {
			if _, ok, _ := f.byKey(p.IdempotencyKey, api.PaymentCompleted); ok {
				return api.Payment{}, false, api.ErrAlreadySettled
			}
		}
		p.Status, p.TxHash, p.ErrorMessage = status, st.TxHash, st.ErrorMessage
		f.w.payments[i] = p
		return p, true, nil
	}
	return api.Payment{}, false, nil
}

func (f fakeStore) sum(agentID string, heldSince *time.Time, keep func(api.Payment) bool) money.Decimal {
	total := money.Zero()
	for _, p := range f.w.payments {
		live := p.Status == api.PaymentPending && heldSince != nil && !p.CreatedAt.Before(*heldSince)
		if p.AgentID == agentID && (p.Status == api.PaymentCompleted || live) && keep(p) {
			total = total.Add(p.Amount)
		}
	}
	return total
}

func (f fakeStore) SumByExecution(_ context.Context, _ db.Session, agentID, executionID string, heldSince *time.Time) (money.Decimal, error) {
	return f.sum(agentID, heldSince, func(p api.Payment) bool { return p.ExecutionID == executionID }), nil
}

func (f fakeStore) SumSince(_ context.Context, _ db.Session, agentID string, since, heldSince *time.Time) (money.Decimal, error) {
	return f.sum(agentID, heldSince, func(p api.Payment) bool { return since == nil || !p.CreatedAt.Before(*since) }), nil
}

func (f fakeStore) ListPayments(context.Context, db.Session, string, domain.PaymentFilter, int32, int32) ([]api.Payment, error) {
	return f.w.payments, nil
}

func (f fakeStore) CountPayments(context.Context, db.Session, string, domain.PaymentFilter) (int, error) {
	return len(f.w.payments), nil
}

type fakeAgents struct{ known map[string]uuid.UUID }

func (f fakeAgents) Resolve(_ context.Context, _ scope.Workspace, s string) (uuid.UUID, bool, error) {
	id, ok := f.known[s]
	return id, ok, nil
}

var now = time.Date(2026, 11, 12, 15, 0, 0, 0, time.UTC)

func newService(t *testing.T) (*Service, *world, scope.Workspace) {
	t.Helper()
	w := &world{wallets: map[uuid.UUID]api.Wallet{}, secrets: map[string]string{}}
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	s := New(Deps{
		DB: fakeDB{w: w}, Store: fakeStore{w}, Agents: fakeAgents{}, Secrets: fakeSecrets{w},
		Log: slog.New(slog.DiscardHandler), Now: func() time.Time { return now },
	})
	return s, w, ws
}

func str(s string) *string { return &s }

const x402 = `{"network": "eip155:8453"}`
const mpp = `{"session_budget_usd": "1"}`

func TestCreateStoresKeysAsJSONUnderTheAgentsSecretName(t *testing.T) {
	s, w, ws := newService(t)
	agent := uuid.New()
	got, err := s.Create(context.Background(), ws, "u1", agent, Create{
		Type: api.TypeDual, X402Config: []byte(x402), MPPConfig: []byte(mpp),
		Credentials: &Credentials{X402PrivateKey: str("0xabc"), MPPTempoKey: str("tk")},
		Budget:      money.MustParse("5"), Period: api.PeriodDaily,
	})
	if err != nil {
		t.Fatal(err)
	}
	name := "wallet_creds_" + agent.String()
	if want := `{"x402_private_key": "0xabc", "mpp_tempo_key": "tk"}`; w.secrets[name] != want {
		t.Fatalf("secret %q, want %q", w.secrets[name], want)
	}
	if got.CredentialsRef == nil || string(*got.CredentialsRef) != name || got.Status != api.StatusActive {
		t.Fatalf("wallet %+v", got)
	}
}

func TestCreateRefusals(t *testing.T) {
	s, w, ws := newService(t)
	agent := uuid.New()
	var ce *domain.ConfigError
	_, err := s.Create(context.Background(), ws, "u", agent, Create{
		Type: api.TypeDual, X402Config: []byte(x402), Credentials: &Credentials{X402PrivateKey: str("0xabc")}, Budget: money.Zero(), Period: api.PeriodExecution,
	})
	if !errors.As(err, &ce) || ce.Message != "mpp_config is required for wallet_type 'dual'" || len(w.secrets) != 0 {
		t.Fatalf("missing config: %v, secrets %v", err, w.secrets)
	}

	ok := Create{Type: api.TypeX402, X402Config: []byte(x402), Credentials: &Credentials{X402PrivateKey: str("0xold")}, Budget: money.Zero(), Period: api.PeriodExecution}
	if _, err := s.Create(context.Background(), ws, "u", agent, ok); err != nil {
		t.Fatal(err)
	}
	ok.Credentials = &Credentials{X402PrivateKey: str("0xnew")}
	if _, err := s.Create(context.Background(), ws, "u", agent, ok); !errors.Is(err, domain.ErrAlreadyExists) {
		t.Fatalf("second wallet: %v", err)
	}
	if got := w.secrets["wallet_creds_"+agent.String()]; !strings.Contains(got, "0xold") {
		t.Fatalf("a refused create replaced the stored key: %q", got)
	}
}

func TestFailedCreateStoresNoKey(t *testing.T) {
	s, w, ws := newService(t)
	w.failMake = errors.New("insert failed")
	agent := uuid.New()
	_, err := s.Create(context.Background(), ws, "u", agent, Create{
		Type: api.TypeX402, X402Config: []byte(x402), Credentials: &Credentials{X402PrivateKey: str("0xabc")}, Budget: money.Zero(), Period: api.PeriodExecution,
	})
	if err == nil || len(w.secrets) != 0 || len(w.wallets) != 0 {
		t.Fatalf("err %v, secrets %v, wallets %d", err, w.secrets, len(w.wallets))
	}
}

func TestUpdateKeepsTheKeyItDoesNotReplace(t *testing.T) {
	s, w, ws := newService(t)
	agent := uuid.New()
	ctx := context.Background()
	if _, err := s.Create(ctx, ws, "u", agent, Create{
		Type: api.TypeDual, X402Config: []byte(x402), MPPConfig: []byte(mpp),
		Credentials: &Credentials{X402PrivateKey: str("0xabc"), MPPTempoKey: str("tk")}, Budget: money.Zero(), Period: api.PeriodExecution,
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Update(ctx, ws, "u", agent, Update{Credentials: &Credentials{X402PrivateKey: str("0xrotated")}}); err != nil {
		t.Fatal(err)
	}
	if want := `{"x402_private_key": "0xrotated", "mpp_tempo_key": "tk"}`; w.secrets["wallet_creds_"+agent.String()] != want {
		t.Fatalf("secret %q, want %q", w.secrets["wallet_creds_"+agent.String()], want)
	}
}

func TestUpdateOnAWalletWithoutKeysStoresThem(t *testing.T) {
	s, w, ws := newService(t)
	agent := uuid.New()
	ctx := context.Background()
	if _, err := s.Create(ctx, ws, "u", agent, Create{Type: api.TypeX402, X402Config: []byte(x402), Budget: money.Zero(), Period: api.PeriodExecution}); err != nil {
		t.Fatal(err)
	}
	got, err := s.Update(ctx, ws, "u", agent, Update{Credentials: &Credentials{X402PrivateKey: str("0xabc")}})
	if err != nil || got.CredentialsRef == nil {
		t.Fatalf("%+v %v", got, err)
	}
	if w.secrets["wallet_creds_"+agent.String()] != `{"x402_private_key": "0xabc"}` {
		t.Fatalf("secret %q", w.secrets["wallet_creds_"+agent.String()])
	}
}

func TestUpdateValidatesTheEffectiveConfig(t *testing.T) {
	s, _, ws := newService(t)
	agent := uuid.New()
	ctx := context.Background()
	if _, err := s.Update(ctx, ws, "u", agent, Update{}); !errors.Is(err, api.ErrNotFound) {
		t.Fatalf("no wallet: %v", err)
	}
	if _, err := s.Create(ctx, ws, "u", agent, Create{Type: api.TypeX402, X402Config: []byte(x402), Budget: money.Zero(), Period: api.PeriodExecution}); err != nil {
		t.Fatal(err)
	}
	var ce *domain.ConfigError
	if _, err := s.Update(ctx, ws, "u", agent, Update{Type: str(api.TypeDual)}); !errors.As(err, &ce) || !strings.Contains(ce.Message, "mpp_config is required") {
		t.Fatalf("dual with one config: %v", err)
	}
	if _, err := s.Update(ctx, ws, "u", agent, Update{Type: str(api.TypeDual), MPPConfig: []byte(mpp)}); err != nil {
		t.Fatalf("dual with both: %v", err)
	}
	if got, err := s.Update(ctx, ws, "u", agent, Update{Type: str(api.TypeMPP)}); err != nil || got.Type != api.TypeMPP {
		t.Fatalf("type change without touching configs: %+v %v", got, err)
	}
}

func TestDeleteRemovesSecretAndWalletTogether(t *testing.T) {
	s, w, ws := newService(t)
	agent := uuid.New()
	ctx := context.Background()
	if _, err := s.Create(ctx, ws, "u", agent, Create{
		Type: api.TypeX402, X402Config: []byte(x402), Credentials: &Credentials{X402PrivateKey: str("0xabc")}, Budget: money.Zero(), Period: api.PeriodExecution,
	}); err != nil {
		t.Fatal(err)
	}
	w.failDel = errors.New("store down")
	if err := s.Delete(ctx, ws, "u", agent); err == nil {
		t.Fatal("a key that cannot be deleted still let the wallet go")
	}
	if len(w.wallets) != 1 || len(w.secrets) != 1 {
		t.Fatalf("wallets %d secrets %d after a failed delete", len(w.wallets), len(w.secrets))
	}
	w.failDel = nil
	if err := s.Delete(ctx, ws, "u", agent); err != nil {
		t.Fatal(err)
	}
	if len(w.wallets) != 0 || len(w.secrets) != 0 {
		t.Fatalf("wallets %d secrets %d after delete", len(w.wallets), len(w.secrets))
	}
	if err := s.Delete(ctx, ws, "u", agent); !errors.Is(err, api.ErrNotFound) {
		t.Fatalf("second delete: %v", err)
	}
}

func pay(w *world, agent uuid.UUID, exec, amount string, at time.Time, status string) {
	w.payments = append(w.payments, api.Payment{
		AgentID: agent.String(), ExecutionID: exec, Amount: money.MustParse(amount), Status: status, CreatedAt: at,
	})
}

func TestBalanceFollowsThePeriod(t *testing.T) {
	ctx := context.Background()
	for name, c := range map[string]struct {
		period    string
		spent     string
		remaining string
	}{
		// An execution-period wallet counts every execution of the agent.
		"execution": {api.PeriodExecution, "6.5", "0"},
		"daily":     {api.PeriodDaily, "4", "1"},
		"monthly":   {api.PeriodMonthly, "5.5", "0"},
	} {
		s, w, ws := newService(t)
		agent := uuid.New()
		if _, err := s.Create(ctx, ws, "u", agent, Create{Type: api.TypeX402, X402Config: []byte(x402), Budget: money.MustParse("5"), Period: c.period}); err != nil {
			t.Fatal(err)
		}
		pay(w, agent, "e1", "4", now.Add(-time.Hour), api.PaymentCompleted)
		pay(w, agent, "e2", "1.5", now.AddDate(0, 0, -3), api.PaymentCompleted)
		pay(w, agent, "e3", "1", now.AddDate(0, -2, 0), api.PaymentCompleted)
		pay(w, agent, "e4", "9", now, api.PaymentFailed)
		b, err := s.Balance(ctx, ws, agent.String())
		if err != nil {
			t.Fatal(err)
		}
		if b.Spent.String() != c.spent || b.Remaining.String() != c.remaining || b.Budget.String() != "5" {
			t.Errorf("%s: spent %s remaining %s budget %s", name, b.Spent, b.Remaining, b.Budget)
		}
	}
}

func TestActiveRemainingCountsPendingReservations(t *testing.T) {
	s, w, ws := newService(t)
	ctx := context.Background()
	agent := uuid.New()
	if _, ok, err := s.Active(ctx, ws, agent.String(), "e1"); err != nil || ok {
		t.Fatalf("no wallet: %v %v", ok, err)
	}
	if _, err := s.Create(ctx, ws, "u", agent, Create{Type: api.TypeX402, X402Config: []byte(x402), Budget: money.MustParse("1"), Period: api.PeriodExecution}); err != nil {
		t.Fatal(err)
	}
	pay(w, agent, "e1", "0.4", now, api.PaymentCompleted)
	pay(w, agent, "e1", "0.2", now, api.PaymentFailed)
	pay(w, agent, "e1", "0.1", now, api.PaymentPending)
	pay(w, agent, "e2", "0.3", now, api.PaymentCompleted)
	p, ok, err := s.Active(ctx, ws, agent.String(), "e1")
	if err != nil || !ok || p.Remaining.String() != "0.5" || p.ExecutionID != "e1" {
		t.Fatalf("active %+v %v %v", p, ok, err)
	}
	pay(w, agent, "e1", "5", now, api.PaymentCompleted)
	if p, _, _ := s.Active(ctx, ws, agent.String(), "e1"); p.Remaining.String() != "0" {
		t.Fatalf("overspent execution has %s left", p.Remaining)
	}
	if _, err := s.Update(ctx, ws, "u", agent, Update{Status: str(api.StatusDisabled)}); err != nil {
		t.Fatal(err)
	}
	if _, ok, _ := s.Active(ctx, ws, agent.String(), "e1"); ok {
		t.Fatal("a disabled wallet pays")
	}
	if _, ok, err := s.Active(ctx, ws, "not-a-uuid", "e1"); ok || err != nil {
		t.Fatalf("garbage agent id: %v %v", ok, err)
	}
}

func TestCredentialsResolveFromTheSecretStore(t *testing.T) {
	s, w, ws := newService(t)
	ctx := context.Background()
	agent := uuid.New()
	name := "wallet_creds_" + agent.String()
	ref := secrets.Ref(name)
	wallet := api.Wallet{AgentID: agent.String(), CredentialsRef: &ref}

	if c, err := s.Credentials(ctx, ws, api.Wallet{}); err != nil || c.X402PrivateKey() != "" {
		t.Fatalf("no ref: %v %v", c, err)
	}
	if c, err := s.Credentials(ctx, ws, wallet); err != nil || c.X402PrivateKey() != "" {
		t.Fatalf("missing secret: %v", err)
	}
	for _, bad := range []string{"", "not json", "[1]", `"s"`} {
		w.secrets[name] = bad
		if c, err := s.Credentials(ctx, ws, wallet); err != nil || c.X402PrivateKey() != "" || c.MPPTempoKey() != "" {
			t.Fatalf("secret %q: %v %v", bad, c, err)
		}
	}
	w.secrets[name] = `{"x402_private_key": "0xabc", "mpp_tempo_key": 7}`
	c, err := s.Credentials(ctx, ws, wallet)
	if err != nil || c.X402PrivateKey() != "0xabc" || c.MPPTempoKey() != "" {
		t.Fatalf("%v %v", c, err)
	}
	if strings.Contains(fmt.Sprintf("%+v %v", c, c), "0xabc") {
		t.Fatal("credentials print their key")
	}
}

func reservation(agent, key, amount string) api.Reservation {
	return api.Reservation{UserID: "u", AgentID: agent, ExecutionID: "e1", Protocol: api.ProtocolX402, IdempotencyKey: key, Amount: money.MustParse(amount)}
}

func TestReserveThenCompleteOrFail(t *testing.T) {
	s, w, ws := newService(t)
	ctx := context.Background()
	agent := uuid.New()
	if _, err := s.Reserve(ctx, ws, reservation(agent.String(), "k", "1")); !errors.Is(err, api.ErrNotFound) {
		t.Fatalf("payment without a wallet: %v", err)
	}
	if _, err := s.Create(ctx, ws, "u", agent, Create{Type: api.TypeX402, X402Config: []byte(x402), Budget: money.MustParse("5"), Period: api.PeriodExecution}); err != nil {
		t.Fatal(err)
	}
	first, err := s.Reserve(ctx, ws, reservation(agent.String(), "k", "1"))
	if err != nil || first.Status != api.PaymentPending {
		t.Fatalf("reserve %+v %v", first, err)
	}
	again, err := s.Reserve(ctx, ws, reservation(agent.String(), "k", "1"))
	if err != nil || again.ID != first.ID || len(w.payments) != 1 {
		t.Fatalf("a retried reservation was not reused: %+v %v (%d rows)", again, err, len(w.payments))
	}
	failed, err := s.Fail(ctx, ws, first.ID, api.Settlement{ErrorMessage: str("signer down")})
	if err != nil || failed.Status != api.PaymentFailed {
		t.Fatalf("fail %+v %v", failed, err)
	}
	if _, err := s.Complete(ctx, ws, first.ID, api.Settlement{}); !errors.Is(err, api.ErrNotReserved) {
		t.Fatalf("completing a failed reservation: %v", err)
	}
	second, err := s.Reserve(ctx, ws, reservation(agent.String(), "k", "1"))
	if err != nil || second.ID == first.ID {
		t.Fatalf("retry after a failure: %+v %v", second, err)
	}
	done, err := s.Complete(ctx, ws, second.ID, api.Settlement{TxHash: str("0xtx")})
	if err != nil || done.Status != api.PaymentCompleted || done.TxHash == nil || *done.TxHash != "0xtx" {
		t.Fatalf("complete %+v %v", done, err)
	}
	if _, err := s.Reserve(ctx, ws, reservation(agent.String(), "k", "1")); !errors.Is(err, api.ErrAlreadySettled) {
		t.Fatalf("reserving a settled key: %v", err)
	}
	if _, err := s.Complete(ctx, ws, "nope", api.Settlement{}); !errors.Is(err, api.ErrNotReserved) {
		t.Fatalf("garbage id: %v", err)
	}
	got, ok, _ := s.FindSettled(ctx, ws, "k")
	if !ok || got.ID != second.ID {
		t.Fatalf("settled %+v %v", got, ok)
	}
	if _, ok, _ := s.FindSettled(ctx, ws, "other"); ok {
		t.Fatal("unknown key settled")
	}
}

func TestReserveRefusesPastTheBudgetAndOnADisabledWallet(t *testing.T) {
	s, w, ws := newService(t)
	ctx := context.Background()
	agent := uuid.New()
	if _, err := s.Create(ctx, ws, "u", agent, Create{Type: api.TypeX402, X402Config: []byte(x402), Budget: money.MustParse("1"), Period: api.PeriodDaily}); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Reserve(ctx, ws, reservation(agent.String(), "a", "0.6")); err != nil {
		t.Fatal(err)
	}
	_, err := s.Reserve(ctx, ws, reservation(agent.String(), "b", "0.5"))
	var be *api.BudgetError
	if !errors.Is(err, api.ErrBudgetExceeded) || !errors.As(err, &be) || be.Remaining.Cmp(money.MustParse("0.4")) != 0 || be.Amount.Plain() != "0.500000" {
		t.Fatalf("over a pending hold: %v", err)
	}
	if _, err := s.Reserve(ctx, ws, reservation(agent.String(), "c", "0.4")); err != nil {
		t.Fatalf("exact fit: %v", err)
	}
	if b, _ := s.Balance(ctx, ws, agent.String()); b.Spent.String() != "0" || b.Remaining.String() != "0" {
		t.Fatalf("balance with holds: spent %s remaining %s", b.Spent, b.Remaining)
	}
	if _, err := s.Fail(ctx, ws, w.payments[0].ID, api.Settlement{}); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Reserve(ctx, ws, reservation(agent.String(), "b", "0.5")); err != nil {
		t.Fatalf("a failed hold released nothing: %v", err)
	}
	if _, err := s.Update(ctx, ws, "u", agent, Update{Status: str(api.StatusDisabled)}); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Reserve(ctx, ws, reservation(agent.String(), "d", "0")); !errors.Is(err, api.ErrWalletDisabled) {
		t.Fatalf("disabled wallet: %v", err)
	}
}

func TestReserveRefusesWhatTheLedgerCannotHold(t *testing.T) {
	s, _, ws := newService(t)
	ok := reservation(uuid.NewString(), "k", "1")
	for name, mutate := range map[string]func(*api.Reservation){
		"protocol":  func(r *api.Reservation) { r.Protocol = "unknown" },
		"negative":  func(r *api.Reservation) { r.Amount = money.MustParse("-1") },
		"too large": func(r *api.Reservation) { r.Amount = money.MustParse("1E+12") },
		"huge":      func(r *api.Reservation) { r.Amount = money.MustParse("1E+2000000000") },
		"rounds up": func(r *api.Reservation) { r.Amount = money.MustParse("999999999999.9999995") },
		"empty key": func(r *api.Reservation) { r.IdempotencyKey = "" },
	} {
		r := ok
		mutate(&r)
		if _, err := s.Reserve(context.Background(), ws, r); err == nil || errors.Is(err, api.ErrNotFound) {
			t.Errorf("%s: %v", name, err)
		}
	}
}

func TestAgentsFromResolvesUUIDsAndOptionallySlugs(t *testing.T) {
	ctx := context.Background()
	ws, _ := scope.NewWorkspace(uuid.NewString(), "acme")
	id := uuid.New()
	l := &lookup{exists: map[string]bool{id.String(): true}, slugs: map[string]string{"my-agent": id.String()}}
	a := AgentsFrom(l)
	if got, ok, err := a.Resolve(ctx, ws, strings.ToUpper(id.String())); err != nil || !ok || got != id {
		t.Fatalf("uuid %v %v %v", got, ok, err)
	}
	if _, ok, _ := a.Resolve(ctx, ws, uuid.NewString()); ok {
		t.Fatal("an unknown uuid resolved")
	}
	if got, ok, err := a.Resolve(ctx, ws, "my-agent"); err != nil || !ok || got != id {
		t.Fatalf("slug %v %v %v", got, ok, err)
	}
	if _, ok, _ := a.Resolve(ctx, ws, "nobody"); ok {
		t.Fatal("an unknown slug resolved")
	}
}

func TestReserveStoresTheWalletsCanonicalAgentID(t *testing.T) {
	s, w, ws := newService(t)
	ctx := context.Background()
	agent := uuid.New()
	if _, err := s.Create(ctx, ws, "u", agent, Create{Type: api.TypeX402, X402Config: []byte(x402), Budget: money.MustParse("5"), Period: api.PeriodDaily}); err != nil {
		t.Fatal(err)
	}
	for i, form := range []string{strings.ToUpper(agent.String()), "{" + agent.String() + "}", "urn:uuid:" + agent.String(), strings.ReplaceAll(agent.String(), "-", "")} {
		p, err := s.Reserve(ctx, ws, reservation(form, fmt.Sprint("k", i), "1"))
		if err != nil {
			t.Fatalf("%s: %v", form, err)
		}
		if _, err := s.Complete(ctx, ws, p.ID, api.Settlement{}); err != nil {
			t.Fatal(err)
		}
	}
	for _, p := range w.payments {
		if p.AgentID != agent.String() {
			t.Fatalf("payment stored agent_id %q, want %q", p.AgentID, agent.String())
		}
	}
	if b, _ := s.Balance(ctx, ws, agent.String()); b.Spent.String() != "4.000000" {
		t.Fatalf("spent %s, want 4", b.Spent)
	}
}

func TestUpdateFailsWhenTheStoredKeysCannotBeRead(t *testing.T) {
	s, w, ws := newService(t)
	ctx := context.Background()
	agent := uuid.New()
	if _, err := s.Create(ctx, ws, "u", agent, Create{
		Type: api.TypeDual, X402Config: []byte(x402), MPPConfig: []byte(mpp),
		Credentials: &Credentials{X402PrivateKey: str("0xabc"), MPPTempoKey: str("tk")}, Budget: money.Zero(), Period: api.PeriodExecution,
	}); err != nil {
		t.Fatal(err)
	}
	w.failGet = errors.New("store down")
	if _, err := s.Update(ctx, ws, "u", agent, Update{Credentials: &Credentials{X402PrivateKey: str("0xrotated")}}); !errors.Is(err, w.failGet) {
		t.Fatalf("unreadable keys: %v", err)
	}
	w.failGet = nil
	if want := `{"x402_private_key": "0xabc", "mpp_tempo_key": "tk"}`; w.secrets["wallet_creds_"+agent.String()] != want {
		t.Fatalf("secret %q, want %q", w.secrets["wallet_creds_"+agent.String()], want)
	}
	delete(w.secrets, "wallet_creds_"+agent.String())
	if _, err := s.Update(ctx, ws, "u", agent, Update{Credentials: &Credentials{X402PrivateKey: str("0xnew")}}); err != nil {
		t.Fatalf("missing secret is empty: %v", err)
	}
}

func TestReserveQuantizesTheAmountToTheColumn(t *testing.T) {
	s, w, ws := newService(t)
	ctx := context.Background()
	agent := uuid.New()
	if _, err := s.Create(ctx, ws, "u", agent, Create{Type: api.TypeX402, X402Config: []byte(x402), Budget: money.MustParse("5"), Period: api.PeriodExecution}); err != nil {
		t.Fatal(err)
	}
	for i, c := range []struct{ in, want string }{{"0.0000015", "0.000002"}, {"1.2", "1.200000"}, {"1E-2000000000", "0.000000"}} {
		if _, err := s.Reserve(ctx, ws, reservation(agent.String(), fmt.Sprint("q", i), c.in)); err != nil {
			t.Fatal(err)
		}
		if got := w.payments[len(w.payments)-1].Amount.Plain(); got != c.want {
			t.Errorf("%s stored as %s, want %s", c.in, got, c.want)
		}
	}
}

func TestExternalSecretFollowsTheRow(t *testing.T) {
	ctx := context.Background()
	keyed := Create{Type: api.TypeX402, X402Config: []byte(x402), Credentials: &Credentials{X402PrivateKey: str("0xabc")}, Budget: money.Zero(), Period: api.PeriodExecution}
	boom := errors.New("boom")

	t.Run("create insert fails", func(t *testing.T) {
		s, w, ws := newService(t)
		w.external, w.failMake = true, boom
		if _, err := s.Create(ctx, ws, "u", uuid.New(), keyed); !errors.Is(err, boom) || len(w.secrets) != 0 {
			t.Fatalf("err %v, secrets %v", err, w.secrets)
		}
	})
	t.Run("create commit fails", func(t *testing.T) {
		s, w, ws := newService(t)
		w.external, w.failCommit = true, boom
		if _, err := s.Create(ctx, ws, "u", uuid.New(), keyed); !errors.Is(err, boom) || len(w.secrets) != 0 || len(w.wallets) != 0 {
			t.Fatalf("err %v, secrets %v, wallets %d", err, w.secrets, len(w.wallets))
		}
	})
	t.Run("create refused keeps the existing key", func(t *testing.T) {
		s, w, ws := newService(t)
		w.external = true
		agent := uuid.New()
		if _, err := s.Create(ctx, ws, "u", agent, keyed); err != nil {
			t.Fatal(err)
		}
		again := keyed
		again.Credentials = &Credentials{X402PrivateKey: str("0xnew")}
		if _, err := s.Create(ctx, ws, "u", agent, again); !errors.Is(err, domain.ErrAlreadyExists) {
			t.Fatal(err)
		}
		if got := w.secrets["wallet_creds_"+agent.String()]; !strings.Contains(got, "0xabc") {
			t.Fatalf("secret %q", got)
		}
	})
	t.Run("update row fails", func(t *testing.T) {
		s, w, ws := newService(t)
		w.external = true
		agent := uuid.New()
		if _, err := s.Create(ctx, ws, "u", agent, keyed); err != nil {
			t.Fatal(err)
		}
		w.failUpdate = boom
		if _, err := s.Update(ctx, ws, "u", agent, Update{Credentials: &Credentials{X402PrivateKey: str("0xrotated")}}); !errors.Is(err, boom) {
			t.Fatal(err)
		}
		if got := w.secrets["wallet_creds_"+agent.String()]; !strings.Contains(got, "0xabc") {
			t.Fatalf("a failed update rotated the key: %q", got)
		}
	})
	t.Run("delete row fails", func(t *testing.T) {
		s, w, ws := newService(t)
		w.external = true
		agent := uuid.New()
		if _, err := s.Create(ctx, ws, "u", agent, keyed); err != nil {
			t.Fatal(err)
		}
		w.failDrop = boom
		if err := s.Delete(ctx, ws, "u", agent); !errors.Is(err, boom) || len(w.secrets) != 1 || len(w.wallets) != 1 {
			t.Fatalf("err %v, secrets %d, wallets %d", err, len(w.secrets), len(w.wallets))
		}
		w.failDrop, w.failDel = nil, boom
		if err := s.Delete(ctx, ws, "u", agent); !errors.Is(err, boom) || len(w.secrets) != 1 || len(w.wallets) != 1 {
			t.Fatalf("secret delete failed: err %v, secrets %d, wallets %d", err, len(w.secrets), len(w.wallets))
		}
	})
}

func TestAStaleReservationStopsHoldingBudget(t *testing.T) {
	s, w, ws := newService(t)
	ctx := context.Background()
	clock := now
	s.d.Now = func() time.Time { return clock }
	agent := uuid.New()
	if _, err := s.Create(ctx, ws, "u", agent, Create{Type: api.TypeX402, X402Config: []byte(x402), Budget: money.MustParse("1"), Period: api.PeriodMonthly}); err != nil {
		t.Fatal(err)
	}
	stale, err := s.Reserve(ctx, ws, reservation(agent.String(), "k", "1"))
	if err != nil {
		t.Fatal(err)
	}
	clock = clock.Add(api.ReservationHold - time.Second)
	if p, _, _ := s.Active(ctx, ws, agent.String(), "e1"); p.Remaining.String() != "0" {
		t.Fatalf("a fresh hold left %s", p.Remaining)
	}
	clock = clock.Add(2 * time.Second)
	if p, _, _ := s.Active(ctx, ws, agent.String(), "e1"); p.Remaining.String() != "1" {
		t.Fatalf("a hold of a dead run still holds: %s left", p.Remaining)
	}
	again, err := s.Reserve(ctx, ws, reservation(agent.String(), "k", "1"))
	if err != nil || again.ID == stale.ID {
		t.Fatalf("retry after the hold expired: %+v %v", again, err)
	}
	if _, err := s.Fail(ctx, ws, again.ID, api.Settlement{}); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Complete(ctx, ws, stale.ID, api.Settlement{TxHash: str("0xlate")}); err != nil {
		t.Fatalf("completing an expired hold: %v", err)
	}
	if b, _ := s.Balance(ctx, ws, agent.String()); b.Spent.String() != "1.000000" || b.Remaining.String() != "0" {
		t.Fatalf("a late settlement does not count: spent %s remaining %s", b.Spent, b.Remaining)
	}
	if len(w.payments) != 2 {
		t.Fatalf("%d rows", len(w.payments))
	}
}
