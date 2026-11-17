package domain

import (
	"errors"
	"fmt"
	"slices"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/wallet/api"
)

// Enum values the routes accept, in the order Python's enums list them.
func WalletTypes() []string { return []string{api.TypeX402, api.TypeMPP, api.TypeDual} }
func BudgetPeriods() []string {
	return []string{api.PeriodExecution, api.PeriodDaily, api.PeriodMonthly}
}
func Statuses() []string { return []string{api.StatusActive, api.StatusDisabled} }

// ErrAlreadyExists: the agent has a wallet in the workspace already.
var ErrAlreadyExists = errors.New("wallet already exists for this agent")

// ErrAgentNotFound: the path names no agent in the caller's workspace.
var ErrAgentNotFound = errors.New("agent not found")

// ConfigError is a ValueError of the wallet service: a config the wallet
// type requires is missing. The message is the 400's detail.
type ConfigError struct{ Message string }

func (e *ConfigError) Error() string { return e.Message }

// ValidateConfig is _validate_config: the configs a wallet type requires.
func ValidateConfig(walletType string, hasX402, hasMPP bool) error {
	if (walletType == api.TypeX402 || walletType == api.TypeDual) && !hasX402 {
		return &ConfigError{Message: fmt.Sprintf("x402_config is required for wallet_type '%s'", walletType)}
	}
	if (walletType == api.TypeMPP || walletType == api.TypeDual) && !hasMPP {
		return &ConfigError{Message: fmt.Sprintf("mpp_config is required for wallet_type '%s'", walletType)}
	}
	return nil
}

// New is a wallet to insert; Budget is the plain decimal text.
type New struct {
	Type           string
	X402Config     []byte
	MPPConfig      []byte
	CredentialsRef *string
	Budget         string
	Period         string
}

// Patch is the fields a wallet update writes; nil leaves a field as it is.
type Patch struct {
	Type           *string
	X402Config     []byte
	MPPConfig      []byte
	CredentialsRef *string
	Budget         *string
	Period         *string
	Status         *string
}

// PaymentFilter narrows a payment listing; From and To bound created_at
// inclusively as naive UTC.
type PaymentFilter struct {
	Protocol *string
	Status   *string
	From     *time.Time
	To       *time.Time
}

// PeriodStart is the instant a daily or monthly budget period began, as naive
// UTC; ok is false for any other period, which sums all time.
func PeriodStart(period string, now time.Time) (time.Time, bool) {
	n := now.UTC()
	switch period {
	case api.PeriodDaily:
		return time.Date(n.Year(), n.Month(), n.Day(), 0, 0, 0, 0, time.UTC), true
	case api.PeriodMonthly:
		return time.Date(n.Year(), n.Month(), 1, 0, 0, 0, 0, time.UTC), true
	}
	return time.Time{}, false
}

// Valid reports whether v is one of the allowed values.
func Valid(allowed []string, v string) bool { return slices.Contains(allowed, v) }
