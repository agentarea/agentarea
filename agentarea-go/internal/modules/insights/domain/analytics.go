// Package domain of insights: entities and rules; standard library and this module only.
package domain

// CollectorURL is where analytics events are sent (analytics/constants.py).
const CollectorURL = "https://analytics.agentarea.ai"

// Analytics is GET /v1/analytics: whether usage analytics is on and, if so,
// the installation id, collector and edition. The three are nil when off.
type Analytics struct {
	Enabled      bool
	InstallID    *string
	CollectorURL *string
	Edition      *string
}

// Balance is the paying account's balance as the caller may see it. Amount is
// nil unless the caller is the payer; RunwayDays is nil when nothing was
// debited in the window. Amounts are decimal strings.
type Balance struct {
	Currency      string
	Exhausted     bool
	ViewerIsPayer bool
	Amount        *string
	SpendPerDay   *string
	RunwayDays    *string
}
