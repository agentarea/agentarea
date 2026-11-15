package payment

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"maps"
	"net/http"
	"slices"
	"sync"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	walletapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/api"
)

// challengeLimit bounds how much of a 402 body is read.
const challengeLimit = 1 << 20

// Payment is one payment a call made or tried.
type Payment = api.Payment

// Call is one tool call that may pay: whose wallet pays and how its payments
// are keyed, identically on every retry of the call.
type Call struct {
	Workspace   scope.Workspace
	UserID      string
	AgentID     string
	ExecutionID string
	CallRef     string
	ToolName    string
	ToolCallID  string
}

// Session pays the 402s of one call through the agent's wallet
// (AgentAreaPaymentTransport). One session serves one call; its round trips
// pay one challenge at a time, so the payment sequence is stable.
type Session struct {
	wallets   walletapi.Wallets
	protocols Protocols
	call      Call
	log       *slog.Logger

	mu       sync.Mutex
	seq      int
	payments []Payment
	looked   bool
	payable  walletapi.Payable
	has      bool
}

// NewSession is the payment side of call; nil wallets make a session that
// never pays.
func NewSession(wallets walletapi.Wallets, protocols Protocols, call Call, log *slog.Logger) *Session {
	if log == nil {
		log = slog.Default()
	}
	return &Session{wallets: wallets, protocols: protocols, call: call, log: log}
}

// Payments are the payments the call made or tried, in order.
func (s *Session) Payments() []Payment {
	if s == nil {
		return nil
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]Payment(nil), s.payments...)
}

// Wrap is inner with the 402s it answers paid and retried through inner.
func (s *Session) Wrap(inner http.RoundTripper) http.RoundTripper {
	if s == nil || s.wallets == nil || s.call.AgentID == "" || s.call.CallRef == "" {
		return inner
	}
	return roundTripper{s: s, inner: inner}
}

type roundTripper struct {
	s     *Session
	inner http.RoundTripper
}

func (rt roundTripper) RoundTrip(req *http.Request) (*http.Response, error) {
	resp, err := rt.inner.RoundTrip(req)
	if err != nil || resp.StatusCode != http.StatusPaymentRequired {
		return resp, err
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, challengeLimit))
	_ = resp.Body.Close()
	resp.Body = io.NopCloser(bytes.NewReader(body))
	if err != nil {
		return resp, nil
	}
	return rt.s.pay(req, resp, body, rt.inner), nil
}

func flatHeaders(h http.Header) map[string]string {
	out := make(map[string]string, len(h))
	for k, v := range h {
		if len(v) > 0 {
			out[k] = v[0]
		}
	}
	return out
}

func (s *Session) record(p Payment) {
	s.payments = append(s.payments, p)
}

// pay answers one 402: the retried response when a payment was made, else
// the 402 itself.
func (s *Session) pay(req *http.Request, resp *http.Response, body []byte, inner http.RoundTripper) *http.Response {
	ctx := req.Context()
	protocol := walletapi.DetectProtocol(resp.StatusCode, flatHeaders(resp.Header))
	if protocol == "" {
		return resp
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	payable, ok, err := s.wallet(ctx)
	if err != nil {
		s.log.ErrorContext(ctx, "the agent's wallet could not be read; the 402 stands", "agent_id", s.call.AgentID, "error", err)
		return resp
	}
	if !ok {
		return resp
	}
	key := walletapi.IdempotencyKey(s.call.CallRef, s.seq)
	s.seq++
	if settled, found, err := s.wallets.FindSettled(ctx, s.call.Workspace, key); err != nil {
		s.log.ErrorContext(ctx, "could not check whether the request was paid already; the 402 stands", "idempotency_key", key, "error", err)
		return resp
	} else if found {
		s.log.WarnContext(ctx, "payment already settled for this tool call; not paying again", "idempotency_key", key, "tool_call_id", s.call.ToolCallID)
		tx := ""
		if settled.TxHash != nil {
			tx = *settled.TxHash
		}
		s.record(Payment{Protocol: settled.Protocol, Amount: settled.Amount, Recipient: settled.Recipient, TxHash: tx,
			IdempotencyKey: key, AlreadySettled: true,
			Error: fmt.Sprintf("This request was already paid (tx %s) by an earlier attempt of the same tool call; not paying again", tx)})
		return resp
	}
	w, err := s.walletOf(ctx, payable.Wallet)
	if err != nil {
		s.log.ErrorContext(ctx, "the wallet's keys could not be read; the 402 stands", "agent_id", s.call.AgentID, "error", err)
		s.record(Payment{Protocol: protocol, IdempotencyKey: key, Error: "the wallet's keys could not be read"})
		return resp
	}
	q, err := s.protocols.Quote(ctx, protocol, w, Challenge{Header: resp.Header.Clone(), Body: body}, key)
	if errors.Is(err, ErrUnsupported) {
		s.log.InfoContext(ctx, "the wallet cannot pay this challenge; the 402 stands", "protocol", protocol, "reason", err)
		return resp
	}
	if err != nil {
		s.log.WarnContext(ctx, "payment challenge could not be read", "protocol", protocol, "error", err)
		s.record(Payment{Protocol: protocol, IdempotencyKey: key, Error: err.Error()})
		return resp
	}
	refuse := func(msg string) *http.Response {
		s.record(Payment{Protocol: q.Protocol, Amount: q.Amount, Recipient: q.Recipient, IdempotencyKey: key, Network: network(q), Error: msg})
		return resp
	}
	if q.Amount.Sign() <= 0 {
		return refuse(fmt.Sprintf("the challenge asks for %s, not a payment", q.Amount))
	}
	if q.Limit != nil && q.Amount.Cmp(*q.Limit) > 0 {
		return refuse(fmt.Sprintf("Payment $%s exceeds session budget $%s", q.Amount, *q.Limit))
	}
	meta, err := json.Marshal(q.Metadata)
	if err != nil {
		return refuse(err.Error())
	}
	hold, err := s.wallets.Reserve(ctx, s.call.Workspace, walletapi.Reservation{
		UserID: s.call.UserID, AgentID: s.call.AgentID, ExecutionID: payable.ExecutionID, Protocol: q.Protocol,
		Amount: q.Amount, Recipient: q.Recipient, ToolName: s.call.ToolName, ToolCallID: s.call.ToolCallID,
		IdempotencyKey: key, ProtocolMetadata: meta,
	})
	var budget *walletapi.BudgetError
	switch {
	case errors.As(err, &budget):
		return refuse(fmt.Sprintf("Payment $%s exceeds remaining budget $%s", budget.Amount, budget.Remaining))
	case errors.Is(err, walletapi.ErrAlreadySettled):
		s.record(Payment{Protocol: q.Protocol, Amount: q.Amount, Recipient: q.Recipient, IdempotencyKey: key, AlreadySettled: true,
			Error: "This request was already paid by an earlier attempt of the same tool call; not paying again"})
		return resp
	case errors.Is(err, walletapi.ErrNotFound), errors.Is(err, walletapi.ErrWalletDisabled):
		return resp
	case err != nil:
		s.log.ErrorContext(ctx, "payment could not be reserved; the 402 stands", "idempotency_key", key, "error", err)
		return refuse("the payment could not be reserved")
	}
	end := context.WithoutCancel(ctx)
	fail := func(msg string) *http.Response {
		if _, err := s.wallets.Fail(end, s.call.Workspace, hold.ID, walletapi.Settlement{ErrorMessage: &msg}); err != nil {
			s.log.ErrorContext(ctx, "reserved payment could not be released; it expires", "payment_id", hold.ID, "error", err)
		}
		return refuse(msg)
	}
	if hold.Amount.Cmp(q.Amount) < 0 {
		return refuse(fmt.Sprintf("The challenge asks $%s, more than the $%s an earlier attempt of this tool call holds; not paying over it", q.Amount, hold.Amount))
	}
	var signed http.Header
	if hold.Signed == nil {
		if signed, err = q.Answer(ctx); err != nil {
			s.log.WarnContext(ctx, "payment could not be signed", "protocol", q.Protocol, "error", err)
			return fail(fmt.Sprintf("%s payment error: %v", q.Protocol, err))
		}
		stored, err := s.wallets.Sign(end, s.call.Workspace, hold.ID, signed)
		if errors.Is(err, walletapi.ErrNotReserved) {
			return refuse("the payment's reservation ended before it was sent")
		}
		if err != nil {
			s.log.ErrorContext(ctx, "the signed payment could not be stored; not sending it", "payment_id", hold.ID, "error", err)
			return fail("the signed payment could not be stored")
		}
		hold = stored
	}
	// A hold another attempt signed may have been paid already: its payment is
	// sent again unchanged, never a second one, and stays held whatever the answer.
	replay := !maps.EqualFunc(hold.Signed, signed, slices.Equal[[]string])
	if replay {
		q.Amount, q.Recipient = hold.Amount, hold.Recipient
	}
	retry, err := retryRequest(req, hold.Signed)
	if err != nil {
		if replay {
			return refuse(err.Error())
		}
		return fail(err.Error())
	}
	paid, err := inner.RoundTrip(retry)
	if err != nil {
		// The request may have reached the server and settled: the hold stays
		// signed, and a retry of the call sends the same payment again.
		s.log.ErrorContext(ctx, "paid retry failed in transit; the reservation is kept", "payment_id", hold.ID, "error", err)
		s.record(Payment{Protocol: q.Protocol, Amount: q.Amount, Recipient: q.Recipient, IdempotencyKey: key, Network: network(q),
			Error: "the paid retry failed in transit: " + err.Error()})
		return resp
	}
	tx := Receipt(q.Protocol, paid.Header)
	success := paid.StatusCode >= 200 && paid.StatusCode < 300
	p := Payment{Protocol: q.Protocol, Amount: q.Amount, Recipient: q.Recipient, TxHash: tx, IdempotencyKey: key, Network: network(q)}
	var txPtr *string
	if tx != "" {
		txPtr = &tx
	}
	if walletapi.SettlementStatus(success, tx) != walletapi.PaymentCompleted {
		msg := fmt.Sprintf("Payment retry failed: %d", paid.StatusCode)
		if replay {
			s.log.WarnContext(ctx, "a payment sent again was not settled by this answer; the reservation is kept", "payment_id", hold.ID, "status", paid.StatusCode)
			p.Error = msg
			s.record(p)
			return paid
		}
		if _, err := s.wallets.Fail(end, s.call.Workspace, hold.ID, walletapi.Settlement{ErrorMessage: &msg}); err != nil {
			s.log.ErrorContext(ctx, "reserved payment could not be released; it expires", "payment_id", hold.ID, "error", err)
		}
		p.Error = msg
		s.record(p)
		return paid
	}
	var st walletapi.Settlement
	st.TxHash = txPtr
	if !success {
		msg := fmt.Sprintf("Payment retry failed: %d", paid.StatusCode)
		st.ErrorMessage, p.Error = &msg, msg
	}
	if _, err := s.wallets.Complete(end, s.call.Workspace, hold.ID, st); err != nil {
		if errors.Is(err, walletapi.ErrAlreadySettled) {
			p.AlreadySettled = true
		} else {
			s.log.ErrorContext(ctx, "a settled payment could not be recorded completed", "payment_id", hold.ID, "tx_hash", tx, "error", err)
		}
	}
	p.Settled = !p.AlreadySettled
	s.record(p)
	return paid
}

// wallet is the agent's active wallet, read once per call (get_payment_context).
func (s *Session) wallet(ctx context.Context) (walletapi.Payable, bool, error) {
	if !s.looked {
		p, ok, err := s.wallets.Active(ctx, s.call.Workspace, s.call.AgentID, s.call.ExecutionID)
		if err != nil {
			return walletapi.Payable{}, false, err
		}
		s.looked, s.payable, s.has = true, p, ok
	}
	return s.payable, s.has, nil
}

func (s *Session) walletOf(ctx context.Context, w walletapi.Wallet) (Wallet, error) {
	keys, err := s.wallets.Credentials(ctx, s.call.Workspace, w)
	if err != nil {
		return Wallet{}, err
	}
	out := Wallet{Type: w.Type, Keys: keys}
	for raw, dst := range map[*json.RawMessage]*map[string]any{&w.X402Config: &out.X402Config, &w.MPPConfig: &out.MPPConfig} {
		if len(*raw) == 0 || string(*raw) == "null" {
			continue
		}
		dec := json.NewDecoder(bytes.NewReader(*raw))
		dec.UseNumber()
		if err := dec.Decode(dst); err != nil {
			return Wallet{}, fmt.Errorf("wallet %s config: %w", w.ID, err)
		}
	}
	return out, nil
}

func network(q Quote) string {
	n, _ := q.Metadata["network"].(string)
	return n
}

// retryRequest is req again with the payment headers, its body replayed.
func retryRequest(req *http.Request, headers http.Header) (*http.Request, error) {
	retry := req.Clone(req.Context())
	if req.Body != nil && req.Body != http.NoBody {
		if req.GetBody == nil {
			return nil, errors.New("the request body cannot be sent again with the payment")
		}
		body, err := req.GetBody()
		if err != nil {
			return nil, err
		}
		retry.Body = body
	}
	for k, v := range headers {
		retry.Header[k] = v
	}
	return retry, nil
}
