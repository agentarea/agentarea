package money

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
)

// Currency is an ISO 4217 code ("USD", "RUB").
type Currency string

// ParseCurrency accepts exactly three uppercase ASCII letters.
func ParseCurrency(s string) (Currency, error) {
	if len(s) != 3 {
		return "", fmt.Errorf("currency %q is not an ISO 4217 code", s)
	}
	for i := range 3 {
		if s[i] < 'A' || s[i] > 'Z' {
			return "", fmt.Errorf("currency %q is not an ISO 4217 code", s)
		}
	}
	return Currency(s), nil
}

const spendCurrencyEnv = "AGENTAREA_SPEND_CURRENCY"

// LoadSpendCurrency reads the one currency spend caps count and tool costs are
// declared in (config/spend.py, default USD). With billing installed it must
// equal billing's ledger currency or the process refuses to start
// (SpendCurrencyMismatchError).
func LoadSpendCurrency(l *config.Loader) Currency {
	raw := l.StringEnv(spendCurrencyEnv, "USD")
	c, err := ParseCurrency(raw)
	if err != nil {
		l.Fail(spendCurrencyEnv, err)
	}
	return c
}

// SpendCurrencyMismatchError: AGENTAREA_SPEND_CURRENCY names another currency
// than billing's ledger.
type SpendCurrencyMismatchError struct {
	Ledger, Configured Currency
}

func (e *SpendCurrencyMismatchError) Error() string {
	return fmt.Sprintf("billing keeps its ledger in %s but AGENTAREA_SPEND_CURRENCY is %s; set it to %s",
		e.Ledger, e.Configured, e.Ledger)
}

// BillingTimeout bounds one billing round trip; past it billing counts as down.
const BillingTimeout = 5 * time.Second

// BillingKind says what a billed call buys.
type BillingKind string

const (
	// KindTool is a connector's tool.
	KindTool BillingKind = "tool"
	// KindModel is an inference call on a model instance; Tool then names the instance.
	KindModel BillingKind = "model"
)

// Hold refusal codes (HoldDecision.Code when not Allowed).
const (
	CodeNoCredits          = "no_credits"
	CodeToolUnpriced       = "tool_unpriced"
	CodeAccountUnresolved  = "account_unresolved"
	CodeCreditLimitReached = "credit_limit_reached"
)

// Quote codes.
const (
	QuoteOK            = "ok"
	QuoteToolUnpriced  = "tool_unpriced"
	QuoteFXUnavailable = "fx_unavailable"
)

// HoldDecision is billing's answer to Authorize: Allowed with HoldID and the
// held Amount in Currency (the ledger currency), or Code and Reason.
type HoldDecision struct {
	Allowed   bool
	Code      string
	Reason    string
	HoldID    string
	Amount    *Decimal
	Currency  Currency
	ExpiresAt *time.Time
}

// Charge is what a capture charged, in the ledger currency.
type Charge struct {
	Amount   Decimal
	Currency Currency
}

// QuoteLine is a vendor cost to express in the ledger currency; Payer
// "platform" adds markup, "workspace" does not.
type QuoteLine struct {
	Payer          string
	Connector      string
	Tool           string
	VendorCost     Decimal
	VendorCurrency Currency
	Kind           BillingKind
}

// Quote is one line's amount in the ledger currency, or nil with Code.
type Quote struct {
	Amount *Decimal
	Code   string
}

// AuthorizeRequest asks billing to hold the customer amount of an estimated vendor cost.
type AuthorizeRequest struct {
	WorkspaceID    string
	Connector      string
	Tool           string
	VendorCost     Decimal
	VendorCurrency Currency
	Quantity       Decimal
	Unit           string
	IdempotencyKey string
	Kind           BillingKind
}

// CaptureRequest charges the actual vendor cost against a hold.
type CaptureRequest struct {
	HoldID         string
	WorkspaceID    string
	Connector      string
	Tool           string
	VendorCost     Decimal
	VendorCurrency Currency
	Quantity       Decimal
	Unit           string
	IdempotencyKey string
	Metadata       map[string]any
	Kind           BillingKind
}

// ToolBilling charges platform-paid tool and model calls, asked live
// (extensions/tool_billing.py ToolBilling, ADR-0038 §2.4). Nothing is cached:
// every answer is billing's own. Each call is bounded by BillingTimeout by
// the caller. Without one installed nothing is held or charged.
type ToolBilling interface {
	// Currency is the ledger currency.
	Currency() Currency
	// Authorize holds the customer amount of an estimated vendor cost, or
	// refuses. An error means billing could not answer; the caller refuses
	// the call.
	Authorize(ctx context.Context, req AuthorizeRequest) (HoldDecision, error)
	// Capture charges the actual vendor cost against a hold and releases the
	// rest. Idempotent on IdempotencyKey; charges even after the hold expired.
	// A request billing refuses as such wraps ErrBillingRejected.
	Capture(ctx context.Context, req CaptureRequest) (Charge, error)
	// Void releases a hold whose call did not run. Idempotent.
	Void(ctx context.Context, holdID string) error
	// Quote expresses each line in the ledger currency, in order.
	Quote(ctx context.Context, lines []QuoteLine) ([]Quote, error)
}

// CustomerPricing names the billing currency amounts read back are in
// (extensions/customer_pricing.py CustomerPricing). The open default is USD
// at provider cost.
type CustomerPricing interface {
	Currency() Currency
}

// ErrBillingRejected: billing refused the request itself (an invalid request,
// a 4xx answer other than a timeout or rate limit). Sending it again
// unchanged cannot succeed; a ToolBilling wraps it in such errors.
var ErrBillingRejected = errors.New("billing rejected the request")

// ErrComputeUnpriced is ComputePricing's answer while billing prices no
// compute (Python raises LookupError).
var ErrComputeUnpriced = errors.New("reserved compute is not priced")

// ComputePricing is a CustomerPricing that also estimates an hour of reserved
// compute, for display; billing remains the money authority.
type ComputePricing interface {
	CustomerPricing
	PriceComputeHour(ctx context.Context, vcpu, memoryGiB Decimal) (Decimal, error)
}

// USDAtProviderCost is the open default pricing.
type USDAtProviderCost struct{}

// Currency is USD.
func (USDAtProviderCost) Currency() Currency { return "USD" }

// AccountBalance is the payer's balance as the caller may see it
// (extensions/account_balance.py). Amount is nil when the caller is not the
// payer. RunwayDays is nil when nothing was debited in the window.
type AccountBalance struct {
	Currency      Currency
	Exhausted     bool
	ViewerIsPayer bool
	Amount        *Decimal
	SpendPerDay   *Decimal
	RunwayDays    *Decimal
}

// BalanceSource answers the balance of the account paying for the caller's
// workspace. Without one there is no balance: a self-hosted install pays its
// providers directly.
type BalanceSource interface {
	Balance(ctx context.Context, caller authn.Caller) (AccountBalance, error)
}

// WorkspaceUsage is a workspace's runtime usage since an instant
// (extensions/workspace_usage.py). StorageGiB is what it stores now. Quantities
// only, never a price.
type WorkspaceUsage struct {
	CPUCoreHours   Decimal
	MemoryGiBHours Decimal
	StorageGiB     Decimal
}

// UsageSource answers runtime usage. Without one nothing is metered beyond
// the spend ledger.
type UsageSource interface {
	UsageSince(ctx context.Context, workspaceID string, since time.Time) (WorkspaceUsage, error)
}
