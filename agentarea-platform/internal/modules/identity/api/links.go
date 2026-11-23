package api

import (
	"context"
	"errors"
	"time"
)

// ErrAccountTaken: another user holds the messenger account; it is never moved silently.
var ErrAccountTaken = errors.New("the account is linked to another user")

// OfferTTL is how long a link a bot hands an unlinked sender stays redeemable.
const OfferTTL = 30 * time.Minute

// Account is a messenger account as the update that names it shows it; Username and Name are
// what the messenger showed at the time, "" when it showed nothing.
type Account struct {
	Provider   string
	ExternalID string
	Username   string
	Name       string
}

// OfferingBot is the bot that offers a link: the workspace and source it belongs to, and its
// @username ("" when unknown).
type OfferingBot struct {
	WorkspaceID string
	SourceID    string
	Username    string
}

// MessengerLinks is the link handshake a messenger bot runs for its senders
// (identity/linking.py, ExternalIdentityRepository): a code the signed-in
// user asked for, redeemed from the messenger account and confirmed by it;
// or a code the bot offers the account, accepted by a signed-in user.
type MessengerLinks interface {
	// Holder is the user a live account is linked to; false when none.
	Holder(ctx context.Context, provider, externalID string) (string, bool, error)
	// Redeem spends code from the account; the user it names then waits for the
	// account's confirmation. False for an unknown, used or expired code.
	Redeem(ctx context.Context, code, provider, externalID string) (string, bool, error)
	// Confirm links the account to the user it redeemed a code for; false when
	// nothing waits, ErrAccountTaken when another user holds the account.
	Confirm(ctx context.Context, account Account) (string, bool, error)
	// Offer issues a code, good for OfferTTL, that links account to a signed-in
	// member of the bot's workspace who accepts it in the webapp. While a code
	// offered to the account through the same source is unspent, none is issued
	// and issued is false.
	Offer(ctx context.Context, account Account, bot OfferingBot) (code string, issued bool, err error)
	// Describe names the user's account to the sender: the masked email, or
	// "your AgentArea account" when it cannot be read.
	Describe(ctx context.Context, userID string) string
	// Accounts are the external ids of the user's live accounts of provider, the most recently
	// linked first; none when the user linked none.
	Accounts(ctx context.Context, userID, provider string) ([]string, error)
}
