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
	// Offer issues a code, good for OfferTTL, that links account to the
	// signed-in user who accepts it in the webapp; bot is the bot's @username.
	Offer(ctx context.Context, account Account, bot string) (string, error)
	// Describe names the user's account to the sender: the masked email, or
	// "your AgentArea account" when it cannot be read.
	Describe(ctx context.Context, userID string) string
}
