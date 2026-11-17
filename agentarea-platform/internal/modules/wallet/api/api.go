// Package api is what other modules may import from wallet: identifiers and the
// interfaces wallet implements for them. Nothing else of wallet is importable
// (rule 1).
package api

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"math"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
)

// Wallet types, budget periods and statuses as agent_wallets stores them.
const (
	TypeX402 = "x402"
	TypeMPP  = "mpp"
	TypeDual = "dual"

	PeriodExecution = "execution"
	PeriodDaily     = "daily"
	PeriodMonthly   = "monthly"

	StatusActive   = "active"
	StatusDisabled = "disabled"
)

// Payment protocols and payment statuses as payment_records stores them.
const (
	ProtocolX402 = "x402"
	ProtocolMPP  = "mpp"

	PaymentCompleted = "completed"
	PaymentFailed    = "failed"
	PaymentPending   = "pending"
)

// ErrAlreadySettled: a completed payment already carries the idempotency key.
// The paid request must not be paid again.
var ErrAlreadySettled = errors.New("a payment under this idempotency key already settled")

// CredentialsSecretPrefix starts the name of an agent's wallet credentials
// secret; the name is this prefix and the agent's UUID, and naming.go parses
// it back into an owner.
const CredentialsSecretPrefix = "wallet_creds_"

// CredentialsRef is the secret that holds an agent's wallet keys.
func CredentialsRef(agentID string) secrets.Ref {
	return secrets.Ref(CredentialsSecretPrefix + agentID)
}

// Wallet is an agent's wallet. X402Config and MPPConfig are the stored JSON
// objects, nil when the wallet has none. The keys are not here: they are
// behind CredentialsRef, resolved at the moment of use.
type Wallet struct {
	ID             string
	AgentID        string
	WorkspaceID    string
	CreatedBy      string
	Type           string
	X402Config     json.RawMessage
	MPPConfig      json.RawMessage
	CredentialsRef *secrets.Ref
	Budget         money.Decimal
	Period         string
	Status         string
	CreatedAt      time.Time
	UpdatedAt      time.Time
}

// Payment is one payment record. CreatedAt is a naive UTC timestamp.
type Payment struct {
	ID               string
	WalletID         string
	AgentID          string
	ExecutionID      string
	Protocol         string
	Amount           money.Decimal
	Recipient        string
	TxHash           *string
	ToolName         string
	ToolCallID       string
	IdempotencyKey   string
	Status           string
	ErrorMessage     *string
	ProtocolMetadata json.RawMessage
	CreatedAt        time.Time
	// Signed is the payment a pending hold sent, as request headers; nil
	// until it is signed. Only Reserve and Sign read it.
	Signed http.Header
}

// Payable is what a run needs to pay a 402 for an agent: the active wallet
// and the budget left for the execution. Remaining is what Reserve would
// grant now; it is not a hold.
type Payable struct {
	Wallet      Wallet
	ExecutionID string
	Remaining   money.Decimal
}

// Reservation holds budget for one paid request before it is paid. WalletID
// and the stored agent id are not inputs: the agent's wallet in the
// workspace is the only one a payment lands on, under its canonical id.
type Reservation struct {
	// UserID is recorded as created_by; the run acts for it.
	UserID           string
	AgentID          string
	ExecutionID      string
	Protocol         string
	Amount           money.Decimal
	Recipient        string
	ToolName         string
	ToolCallID       string
	IdempotencyKey   string
	ProtocolMetadata json.RawMessage
}

// ReservationHold is how long a pending reservation holds budget: the
// longest a paid tool call runs (the execute_tool activity's StartToClose,
// Python TOOL_EXECUTION_TIMEOUT). A hold older than that belongs to a run
// that died; it stops counting, and completing it still settles the payment.
const ReservationHold = 40 * time.Minute

// Settlement is how a reserved payment ended. A nil ProtocolMetadata keeps
// what the reservation stored.
type Settlement struct {
	TxHash           *string
	ErrorMessage     *string
	ProtocolMetadata json.RawMessage
}

// ErrBudgetExceeded: the reservation does not fit the budget left once
// settled and reserved payments are counted. The error is a *BudgetError.
var ErrBudgetExceeded = errors.New("payment exceeds the wallet's remaining budget")

// BudgetError is a refused reservation: what it asked and what was left.
type BudgetError struct {
	Amount    money.Decimal
	Remaining money.Decimal
}

func (e *BudgetError) Error() string {
	return fmt.Sprintf("payment of %s exceeds the wallet's remaining budget of %s", e.Amount, e.Remaining)
}

// Is makes a BudgetError ErrBudgetExceeded.
func (e *BudgetError) Is(target error) bool { return target == ErrBudgetExceeded }

// ErrWalletDisabled: the agent's wallet exists but is not active.
var ErrWalletDisabled = errors.New("the agent's wallet is disabled")

// ErrNotReserved: no pending reservation has this id in the workspace; it
// was never made or is already completed or failed.
var ErrNotReserved = errors.New("no pending payment reservation with this id")

// Balance is the budget state the balance route shows. Spent counts the
// agent's settled payments of the current period; for an execution-period
// wallet that is every settled payment of the agent. Remaining also takes
// off what pending reservations hold.
type Balance struct {
	Budget    money.Decimal
	Period    string
	Spent     money.Decimal
	Remaining money.Decimal
}

// Exhausted is an active daily or monthly wallet whose period spend and
// pending reservations reached its budget.
type Exhausted struct {
	AgentID string
	Budget  money.Decimal
	Period  string
}

// Credentials are an agent's wallet keys. The value never prints, logs or
// marshals: only the accessors return a key.
type Credentials struct {
	x402 string
	mpp  string
}

// NewCredentials holds the two keys; either may be empty.
func NewCredentials(x402PrivateKey, mppTempoKey string) Credentials {
	return Credentials{x402: x402PrivateKey, mpp: mppTempoKey}
}

// X402PrivateKey is the EVM signing key, empty when none is stored.
func (c Credentials) X402PrivateKey() string { return c.x402 }

// MPPTempoKey is the Tempo key, empty when none is stored.
func (c Credentials) MPPTempoKey() string { return c.mpp }

const redacted = "[redacted wallet credentials]"

// String hides the keys.
func (Credentials) String() string { return redacted }

// GoString hides the keys.
func (Credentials) GoString() string { return redacted }

// LogValue hides the keys from slog.
func (Credentials) LogValue() slog.Value { return slog.StringValue(redacted) }

// MarshalJSON hides the keys.
func (Credentials) MarshalJSON() ([]byte, error) { return json.Marshal(redacted) }

// AgentCredentials is what agents calls as it deletes an agent: the agent's
// wallet row goes with it, the secret holding its keys does not.
type AgentCredentials interface {
	// DeleteCredentials deletes the agent's wallet credentials secret in the
	// session's transaction; an agent that has none changes nothing.
	DeleteCredentials(ctx context.Context, s db.Session, userID, agentID string) error
}

// Wallets is what runs and insights call. Every method acts in ws.
//
// Paying is Reserve, then Complete or Fail: Reserve checks the budget and
// holds the amount under a lock on the wallet, so parallel payments of one
// agent never spend past it.
type Wallets interface {
	// Active is the agent's wallet when it exists and is active, with the
	// budget left for executionID (Python get_payment_context). A missing or
	// disabled wallet is false, not an error.
	Active(ctx context.Context, ws scope.Workspace, agentID, executionID string) (Payable, bool, error)
	// Credentials resolves the wallet's keys from the secret store. A wallet
	// without a secret, or a secret that is not a JSON object, has none.
	Credentials(ctx context.Context, ws scope.Workspace, w Wallet) (Credentials, error)
	// FindSettled is the completed payment already made under key.
	FindSettled(ctx context.Context, ws scope.Workspace, key string) (Payment, bool, error)
	// Reserve holds r.Amount of the agent's budget as a pending payment. It
	// is ErrNotFound without a wallet, ErrWalletDisabled, ErrAlreadySettled
	// when key completed already, and a *BudgetError when the amount does
	// not fit what settled and pending payments leave. A pending reservation
	// under the same key on the wallet is returned again, not doubled: one
	// made within ReservationHold, or a signed one of any age.
	Reserve(ctx context.Context, ws scope.Workspace, r Reservation) (Payment, error)
	// Sign stores the signed payment of a pending hold before it is sent. A
	// hold signed already keeps its payment, and the hold is returned as
	// stored, so concurrent attempts send one payment. ErrNotReserved when the
	// hold is not pending.
	Sign(ctx context.Context, ws scope.Workspace, paymentID string, signed http.Header) (Payment, error)
	// Complete settles the reservation (ErrNotReserved when it is not
	// pending, ErrAlreadySettled when its key settled meanwhile).
	Complete(ctx context.Context, ws scope.Workspace, paymentID string, st Settlement) (Payment, error)
	// Fail ends the reservation unpaid and releases its budget.
	Fail(ctx context.Context, ws scope.Workspace, paymentID string, st Settlement) (Payment, error)
	// Balance is the budget state of the agent's wallet (ErrNotFound without one).
	Balance(ctx context.Context, ws scope.Workspace, agentID string) (Balance, error)
	// Exhausted lists the workspace's wallets whose period budget is spent
	// or held by pending reservations.
	Exhausted(ctx context.Context, ws scope.Workspace) ([]Exhausted, error)
}

// ErrNotFound: the agent has no wallet in the workspace.
var ErrNotFound = errors.New("no wallet configured for this agent")

// IdempotencyKey keys one paid request of a tool call so every retry of the
// activity derives the same key: sha256 hex of "<callRef>:<sequence>", which
// stays inside x402's payment-identifier alphabet and length.
func IdempotencyKey(callRef string, sequence int) string {
	sum := sha256.Sum256([]byte(callRef + ":" + strconv.Itoa(sequence)))
	return hex.EncodeToString(sum[:])
}

// CallRef identifies the tool call a payment belongs to, identically on every
// retry of the activity: "<task>:<tool call>" when both are known, else the
// activity's own identity.
func CallRef(taskID, toolCallID, workflowID, runID, activityID string) string {
	if taskID != "" && toolCallID != "" {
		return taskID + ":" + toolCallID
	}
	return fmt.Sprintf("%s:%s:%s", workflowID, runID, activityID)
}

// SettlementStatus is a payment's status by whether it settled, not by
// whether the paid request succeeded: a settlement receipt on a failed
// request still means the money left.
func SettlementStatus(requestSucceeded bool, txHash string) string {
	if requestSucceeded || txHash != "" {
		return PaymentCompleted
	}
	return PaymentFailed
}

// DetectProtocol names the protocol a 402 response asks for, "" when unknown:
// x402 on a payment-required header, else MPP on a WWW-Authenticate that
// starts with "payment" or mentions "mpp". x402 wins when both are present.
func DetectProtocol(status int, headers map[string]string) string {
	if status != 402 {
		return ""
	}
	auth := ""
	for k, v := range headers {
		switch strings.ToLower(k) {
		case "payment-required":
			return ProtocolX402
		case "www-authenticate":
			auth = strings.ToLower(v)
		}
	}
	if strings.Contains(auth, "mpp") || strings.HasPrefix(auth, "payment") {
		return ProtocolMPP
	}
	return ""
}

// Adjusted is the decimal exponent of d's leading digit (3 for 1234.5, -2 for
// 0.0123), math.MinInt32 for zero. Comparing against a power of ten through
// it never builds a number as large as the exponent says, which a request
// body can set to 10 ** 2147483647.
func Adjusted(d money.Decimal) int64 {
	if d.IsZero() {
		return math.MinInt32
	}
	s := d.String()
	s = strings.TrimLeft(s, "+-")
	mant, _, _ := strings.Cut(s, "E")
	digits := strings.TrimLeft(strings.ReplaceAll(mant, ".", ""), "0")
	return int64(d.Exponent()) + int64(len(digits)) - 1
}
