package api

import "github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"

// Payment is one payment a call made or tried through the agent's wallet
// (the payment dicts of mcp_payment_httpx._payment_result). Settled: the
// money left the wallet.
type Payment struct {
	Protocol       string
	Amount         money.Decimal
	Recipient      string
	TxHash         string
	Network        string
	IdempotencyKey string
	Error          string
	Settled        bool
	// AlreadySettled: an earlier attempt of the call paid this request.
	AlreadySettled bool
}

// PaidCall is what keys a call's payments, identically on every retry of
// the call: its execution (the wallet's budget period) and its call ref.
type PaidCall struct {
	ExecutionID string
	CallRef     string
}
