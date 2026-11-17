package api

import (
	"context"
	"errors"
)

// ErrAccountTaken: another user holds the messenger account; it is never moved silently.
var ErrAccountTaken = errors.New("the account is linked to another user")

// MessengerLinks is the link handshake a messenger bot runs for its senders
// (identity/linking.py, ExternalIdentityRepository): a code the signed-in
// user asked for, redeemed from the messenger account and confirmed by it.
type MessengerLinks interface {
	// Holder is the user a live account is linked to; false when none.
	Holder(ctx context.Context, provider, externalID string) (string, bool, error)
	// Redeem spends code from the account; the user it names then waits for the
	// account's confirmation. False for an unknown, used or expired code.
	Redeem(ctx context.Context, code, provider, externalID string) (string, bool, error)
	// Confirm links the account to the user it redeemed a code for; false when
	// nothing waits, ErrAccountTaken when another user holds the account.
	Confirm(ctx context.Context, provider, externalID string) (string, bool, error)
	// Describe names the user's account to the sender: the masked email, or
	// "your AgentArea account" when it cannot be read.
	Describe(ctx context.Context, userID string) string
}
