package payment

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	walletapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/api"
)

const testKey = "0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318"

type fakeWallets struct {
	mu        sync.Mutex
	none      bool
	wallet    *walletapi.Wallet
	keys      *walletapi.Credentials
	remaining money.Decimal
	settled   map[string]walletapi.Payment
	// holds are the pending reservations by idempotency key, as Reserve
	// returns a pending one again.
	holds     map[string]walletapi.Payment
	reserved  []walletapi.Reservation
	completed []walletapi.Settlement
	failed    []walletapi.Settlement
}

func newFakeWallets(remaining string) *fakeWallets {
	return &fakeWallets{remaining: money.MustParse(remaining), settled: map[string]walletapi.Payment{}, holds: map[string]walletapi.Payment{}}
}

func (f *fakeWallets) Active(context.Context, scope.Workspace, string, string) (walletapi.Payable, bool, error) {
	if f.none {
		return walletapi.Payable{}, false, nil
	}
	w := walletapi.Wallet{ID: "w1", Type: walletapi.TypeX402, Status: walletapi.StatusActive}
	if f.wallet != nil {
		w = *f.wallet
	}
	return walletapi.Payable{Wallet: w, ExecutionID: "exec", Remaining: f.remaining}, true, nil
}

func (f *fakeWallets) Credentials(context.Context, scope.Workspace, walletapi.Wallet) (walletapi.Credentials, error) {
	if f.keys != nil {
		return *f.keys, nil
	}
	return walletapi.NewCredentials(testKey, ""), nil
}

func (f *fakeWallets) FindSettled(_ context.Context, _ scope.Workspace, key string) (walletapi.Payment, bool, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	p, ok := f.settled[key]
	return p, ok, nil
}

func (f *fakeWallets) Reserve(_ context.Context, _ scope.Workspace, r walletapi.Reservation) (walletapi.Payment, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if p, ok := f.holds[r.IdempotencyKey]; ok {
		return p, nil
	}
	if r.Amount.Cmp(f.remaining) > 0 {
		return walletapi.Payment{}, &walletapi.BudgetError{Amount: r.Amount, Remaining: f.remaining}
	}
	f.reserved = append(f.reserved, r)
	p := walletapi.Payment{ID: r.IdempotencyKey, Protocol: r.Protocol, Amount: r.Amount, Recipient: r.Recipient, IdempotencyKey: r.IdempotencyKey}
	f.holds[r.IdempotencyKey] = p
	return p, nil
}

func (f *fakeWallets) Sign(_ context.Context, _ scope.Workspace, id string, signed http.Header) (walletapi.Payment, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	p, ok := f.holds[id]
	if !ok {
		return walletapi.Payment{}, walletapi.ErrNotReserved
	}
	if p.Signed == nil {
		p.Signed = signed
		f.holds[id] = p
	}
	return p, nil
}

func (f *fakeWallets) Complete(_ context.Context, _ scope.Workspace, id string, st walletapi.Settlement) (walletapi.Payment, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	delete(f.holds, id)
	f.completed = append(f.completed, st)
	return walletapi.Payment{}, nil
}

func (f *fakeWallets) Fail(_ context.Context, _ scope.Workspace, id string, st walletapi.Settlement) (walletapi.Payment, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	delete(f.holds, id)
	f.failed = append(f.failed, st)
	return walletapi.Payment{}, nil
}

func (f *fakeWallets) Balance(context.Context, scope.Workspace, string) (walletapi.Balance, error) {
	return walletapi.Balance{}, nil
}

func (f *fakeWallets) Exhausted(context.Context, scope.Workspace) ([]walletapi.Exhausted, error) {
	return nil, nil
}

// paidServer asks for 0.01 USDC over x402 v2 until a request carries a
// signature; then it answers 200 with retryStatus and a settlement receipt
// unless noReceipt.
type paidServer struct {
	*httptest.Server
	mu          sync.Mutex
	bodies      []string
	signatures  []string
	retryStatus int
	noReceipt   bool
}

func newPaidServer(t *testing.T) *paidServer {
	s := &paidServer{retryStatus: http.StatusOK}
	s.Server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		s.mu.Lock()
		s.bodies = append(s.bodies, string(body))
		sig := r.Header.Get("PAYMENT-SIGNATURE")
		if sig != "" {
			s.signatures = append(s.signatures, sig)
		}
		s.mu.Unlock()
		if sig == "" {
			required, _ := json.Marshal(map[string]any{
				"x402Version": 2,
				"resource":    map[string]any{"url": "http://" + r.Host + r.URL.Path},
				"accepts": []any{map[string]any{
					"scheme": "exact", "network": "eip155:8453", "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
					"amount": "10000", "payTo": "0x209693Bc6afc0C5328bA36FaF03C514EF312287C", "maxTimeoutSeconds": 60,
					"extra": map[string]any{"name": "USD Coin", "version": "2"},
				}},
			})
			w.Header().Set("PAYMENT-REQUIRED", base64.StdEncoding.EncodeToString(required))
			w.WriteHeader(http.StatusPaymentRequired)
			_, _ = w.Write([]byte(`{"error":"payment required"}`))
			return
		}
		if !s.noReceipt {
			receipt, _ := json.Marshal(map[string]any{"success": true, "transaction": "0xfeed"})
			w.Header().Set("PAYMENT-RESPONSE", base64.StdEncoding.EncodeToString(receipt))
		}
		w.WriteHeader(s.retryStatus)
		_, _ = w.Write([]byte(`{"answer":42}`))
	}))
	t.Cleanup(s.Close)
	return s
}

func testCall(t *testing.T) Call {
	ws, err := scope.NewWorkspace("ws-1", "")
	if err != nil {
		t.Fatal(err)
	}
	return Call{Workspace: ws, UserID: "u1", AgentID: "a1", ExecutionID: "exec", CallRef: "task:call-1", ToolName: "search", ToolCallID: "call-1"}
}

func session(t *testing.T, w walletapi.Wallets) *Session {
	return NewSession(w, Protocols{Now: func() time.Time { return time.Unix(1_800_000_000, 0) }, Rand: rand.Reader}, testCall(t), nil)
}

func post(t *testing.T, rt http.RoundTripper, url string) *http.Response {
	req, err := http.NewRequestWithContext(context.Background(), http.MethodPost, url, bytes.NewReader([]byte(`{"q":"x"}`)))
	if err != nil {
		t.Fatal(err)
	}
	resp, err := (&http.Client{Transport: rt}).Do(req)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = resp.Body.Close() })
	return resp
}

func TestSessionPaysA402AndReplaysTheRequest(t *testing.T) {
	srv := newPaidServer(t)
	w := newFakeWallets("5")
	s := session(t, w)
	resp := post(t, s.Wrap(http.DefaultTransport), srv.URL+"/search")
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status %d, want the paid answer", resp.StatusCode)
	}
	if body, _ := io.ReadAll(resp.Body); string(body) != `{"answer":42}` {
		t.Fatalf("body %q", body)
	}
	if len(srv.bodies) != 2 || srv.bodies[1] != `{"q":"x"}` {
		t.Fatalf("the paid retry did not carry the body again: %q", srv.bodies)
	}
	sig, err := base64.StdEncoding.DecodeString(srv.signatures[0])
	if err != nil || !strings.Contains(string(sig), `"x402Version":2`) {
		t.Fatalf("signature %q (%v)", sig, err)
	}
	key := walletapi.IdempotencyKey("task:call-1", 0)
	if len(w.reserved) != 1 || w.reserved[0].Amount.String() != "0.01" || w.reserved[0].IdempotencyKey != key ||
		w.reserved[0].ExecutionID != "exec" || w.reserved[0].ToolCallID != "call-1" {
		t.Fatalf("reserved %+v", w.reserved)
	}
	if len(w.completed) != 1 || w.completed[0].TxHash == nil || *w.completed[0].TxHash != "0xfeed" || len(w.failed) != 0 {
		t.Fatalf("completed %+v failed %+v", w.completed, w.failed)
	}
	ps := s.Payments()
	if len(ps) != 1 || !ps[0].Settled || ps[0].TxHash != "0xfeed" || ps[0].Network != "eip155:8453" || ps[0].Error != "" {
		t.Fatalf("payments %+v", ps)
	}
}

func TestSessionRefusesPastTheBudget(t *testing.T) {
	srv := newPaidServer(t)
	w := newFakeWallets("0.005")
	s := session(t, w)
	resp := post(t, s.Wrap(http.DefaultTransport), srv.URL)
	if resp.StatusCode != http.StatusPaymentRequired {
		t.Fatalf("status %d, want the 402", resp.StatusCode)
	}
	if body, _ := io.ReadAll(resp.Body); !strings.Contains(string(body), "payment required") {
		t.Fatalf("the 402 body was lost: %q", body)
	}
	ps := s.Payments()
	if len(ps) != 1 || ps[0].Settled || ps[0].Error != "Payment $0.01 exceeds remaining budget $0.005" {
		t.Fatalf("payments %+v", ps)
	}
	if len(srv.signatures) != 0 || len(w.completed)+len(w.failed) != 0 {
		t.Fatalf("paid past the budget: %d signatures", len(srv.signatures))
	}
}

func TestSessionDoesNotPayARequestPaidBefore(t *testing.T) {
	srv := newPaidServer(t)
	w := newFakeWallets("5")
	tx := "0xold"
	w.settled[walletapi.IdempotencyKey("task:call-1", 0)] = walletapi.Payment{Protocol: "x402", Amount: money.MustParse("0.01"), TxHash: &tx}
	s := session(t, w)
	resp := post(t, s.Wrap(http.DefaultTransport), srv.URL)
	if resp.StatusCode != http.StatusPaymentRequired || len(srv.signatures) != 0 || len(w.reserved) != 0 {
		t.Fatalf("status %d, %d signatures, %d reservations", resp.StatusCode, len(srv.signatures), len(w.reserved))
	}
	ps := s.Payments()
	if len(ps) != 1 || !ps[0].AlreadySettled || ps[0].Settled || ps[0].TxHash != "0xold" {
		t.Fatalf("payments %+v", ps)
	}
}

func TestSessionReleasesAHoldTheServerDidNotSettle(t *testing.T) {
	srv := newPaidServer(t)
	srv.retryStatus, srv.noReceipt = http.StatusBadGateway, true
	w := newFakeWallets("5")
	s := session(t, w)
	resp := post(t, s.Wrap(http.DefaultTransport), srv.URL)
	if resp.StatusCode != http.StatusBadGateway {
		t.Fatalf("status %d", resp.StatusCode)
	}
	if len(w.failed) != 1 || len(w.completed) != 0 {
		t.Fatalf("completed %+v failed %+v", w.completed, w.failed)
	}
	if ps := s.Payments(); len(ps) != 1 || ps[0].Settled || ps[0].Error != "Payment retry failed: 502" {
		t.Fatalf("payments %+v", ps)
	}
}

func TestSessionCountsMoneyThatLeftOnAFailedAnswer(t *testing.T) {
	srv := newPaidServer(t)
	srv.retryStatus = http.StatusInternalServerError
	w := newFakeWallets("5")
	s := session(t, w)
	post(t, s.Wrap(http.DefaultTransport), srv.URL)
	if len(w.completed) != 1 || *w.completed[0].TxHash != "0xfeed" || w.completed[0].ErrorMessage == nil {
		t.Fatalf("completed %+v", w.completed)
	}
	if ps := s.Payments(); len(ps) != 1 || !ps[0].Settled {
		t.Fatalf("payments %+v", ps)
	}
}

func TestSessionLeavesA402WithoutAWallet(t *testing.T) {
	srv := newPaidServer(t)
	w := newFakeWallets("5")
	w.none = true
	s := session(t, w)
	resp := post(t, s.Wrap(http.DefaultTransport), srv.URL)
	if resp.StatusCode != http.StatusPaymentRequired || len(s.Payments()) != 0 {
		t.Fatalf("status %d payments %+v", resp.StatusCode, s.Payments())
	}
}

func TestSessionKeysEveryPaidRequestOfTheCall(t *testing.T) {
	srv := newPaidServer(t)
	w := newFakeWallets("5")
	s := session(t, w)
	rt := s.Wrap(http.DefaultTransport)
	post(t, rt, srv.URL)
	post(t, rt, srv.URL)
	if len(w.reserved) != 2 || w.reserved[0].IdempotencyKey != walletapi.IdempotencyKey("task:call-1", 0) ||
		w.reserved[1].IdempotencyKey != walletapi.IdempotencyKey("task:call-1", 1) {
		t.Fatalf("reserved %+v", w.reserved)
	}
}

func TestWrapWithoutACallRefPaysNothing(t *testing.T) {
	c := testCall(t)
	c.CallRef = ""
	inner := http.DefaultTransport
	if got := NewSession(newFakeWallets("5"), Protocols{}, c, nil).Wrap(inner); got != inner {
		t.Fatal("a call without a ref must not pay")
	}
	var nilSession *Session
	if nilSession.Wrap(inner) != inner || nilSession.Payments() != nil {
		t.Fatal("a nil session must pay nothing")
	}
}

func TestSessionRefusesPastTheMPPSessionBudget(t *testing.T) {
	var seen int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		seen++
		w.Header().Set("WWW-Authenticate", mppHeader(mppRequest, `, expires="2030-01-01T00:00:00Z"`))
		w.WriteHeader(http.StatusPaymentRequired)
	}))
	t.Cleanup(srv.Close)
	w := newFakeWallets("5")
	w.wallet = &walletapi.Wallet{ID: "w1", Type: walletapi.TypeMPP, Status: walletapi.StatusActive,
		MPPConfig: json.RawMessage(`{"session_budget_usd": 0.005, "decimals": 6}`)}
	keys := mppWallet(nil).Keys
	w.keys = &keys
	s := session(t, w)
	resp := post(t, s.Wrap(http.DefaultTransport), srv.URL)
	if resp.StatusCode != http.StatusPaymentRequired || seen != 1 || len(w.reserved) != 0 {
		t.Fatalf("status %d, %d requests, %d reservations", resp.StatusCode, seen, len(w.reserved))
	}
	if ps := s.Payments(); len(ps) != 1 || ps[0].Settled || ps[0].Protocol != "mpp" || ps[0].Error != "Payment $0.01 exceeds session budget $0.005" {
		t.Fatalf("payments %+v", ps)
	}
}

// dropPaid sends a paid request on and then loses its answer, as a
// connection reset after the server settled.
type dropPaid struct{ inner http.RoundTripper }

func (d dropPaid) RoundTrip(req *http.Request) (*http.Response, error) {
	resp, err := d.inner.RoundTrip(req)
	if err != nil || req.Header.Get("PAYMENT-SIGNATURE") == "" {
		return resp, err
	}
	_ = resp.Body.Close()
	return nil, io.ErrUnexpectedEOF
}

func TestARetriedCallSendsTheSamePaymentAgain(t *testing.T) {
	srv := newPaidServer(t)
	w := newFakeWallets("5")
	post(t, session(t, w).Wrap(dropPaid{http.DefaultTransport}), srv.URL)
	if len(srv.signatures) != 1 || len(w.holds) != 1 || len(w.failed)+len(w.completed) != 0 {
		t.Fatalf("%d signatures, holds %+v, failed %+v", len(srv.signatures), w.holds, w.failed)
	}
	retry := session(t, w)
	resp := post(t, retry.Wrap(http.DefaultTransport), srv.URL)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status %d", resp.StatusCode)
	}
	if len(srv.signatures) != 2 || srv.signatures[1] != srv.signatures[0] {
		t.Fatal("the retry signed a second payment instead of sending the first again")
	}
	if len(w.reserved) != 1 || len(w.completed) != 1 {
		t.Fatalf("reserved %d, completed %d", len(w.reserved), len(w.completed))
	}
}

func TestARetryAskingMoreThanItsHoldIsRefused(t *testing.T) {
	srv := newPaidServer(t)
	w := newFakeWallets("5")
	post(t, session(t, w).Wrap(dropPaid{http.DefaultTransport}), srv.URL)
	w.holds[walletapi.IdempotencyKey("task:call-1", 0)] = func() walletapi.Payment {
		p := w.holds[walletapi.IdempotencyKey("task:call-1", 0)]
		p.Amount = money.MustParse("0.005")
		return p
	}()
	retry := session(t, w)
	resp := post(t, retry.Wrap(http.DefaultTransport), srv.URL)
	if resp.StatusCode != http.StatusPaymentRequired || len(srv.signatures) != 1 {
		t.Fatalf("status %d, %d signatures: paid over the hold", resp.StatusCode, len(srv.signatures))
	}
	if ps := retry.Payments(); len(ps) != 1 || !strings.Contains(ps[0].Error, "more than the $0.005") || len(w.failed) != 0 {
		t.Fatalf("payments %+v failed %+v", ps, w.failed)
	}
}

func TestASentPaymentThatIsRefusedOnReplayStaysHeld(t *testing.T) {
	srv := newPaidServer(t)
	w := newFakeWallets("5")
	post(t, session(t, w).Wrap(dropPaid{http.DefaultTransport}), srv.URL)
	srv.retryStatus, srv.noReceipt = http.StatusBadGateway, true
	post(t, session(t, w).Wrap(http.DefaultTransport), srv.URL)
	if len(w.failed) != 0 || len(w.holds) != 1 {
		t.Fatalf("a payment that may have settled was released: failed %+v", w.failed)
	}
}
