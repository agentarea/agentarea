// Package payment answers HTTP 402 challenges a paid MCP or OpenAPI call
// receives (libs/payment, mcp_payment_httpx.py): it reads what a challenge
// asks, signs the payment with the agent's wallet key (x402 exact on EVM,
// MPP charge on Tempo), and retries the request through the same netguard
// transport. The budget is wallet's: every payment is a reservation made
// before signing and completed or failed after the retry.
package payment

import (
	"context"
	"errors"
	"io"
	"net/http"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	walletapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/api"
)

// Wallet is an agent's wallet as the protocols read it. The configs are the
// stored x402_config and mpp_config objects (nil when absent).
type Wallet struct {
	Type       string
	X402Config map[string]any
	MPPConfig  map[string]any
	Keys       walletapi.Credentials
}

// Quote is what one 402 challenge asks and how to answer it.
type Quote struct {
	Protocol string
	// Amount is in USD.
	Amount    money.Decimal
	Recipient string
	// Limit is the most one payment of this protocol may cost under the
	// wallet's config (MPP session_budget_usd); nil when none applies.
	Limit *money.Decimal
	// Metadata is stored as the payment's protocol_metadata.
	Metadata map[string]any
	answer   func(ctx context.Context) (http.Header, error)
}

// Answer signs the payment; the headers go on the retried request.
func (q Quote) Answer(ctx context.Context) (http.Header, error) {
	if q.answer == nil {
		return nil, errors.New("the quote has no way to pay")
	}
	return q.answer(ctx)
}

// ErrUnsupported: the wallet cannot pay this challenge (wrong wallet type,
// no key for the protocol, no method or requirement it can pay). The 402
// stands as the answer and nothing is recorded, as Python returned the
// response unchanged.
var ErrUnsupported = errors.New("the wallet cannot pay this challenge")

// Protocols reads and answers challenges.
type Protocols struct {
	// RPC carries the chain JSON-RPC calls a payment needs (Tempo nonce,
	// gas, chain id); it is a netguard transport.
	RPC  http.RoundTripper
	Now  func() time.Time
	Rand io.Reader
}

// Challenge is a 402 answer: its headers and body.
type Challenge struct {
	Header http.Header
	Body   []byte
}
