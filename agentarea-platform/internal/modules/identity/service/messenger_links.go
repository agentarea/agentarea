package service

import (
	"context"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
)

// How a link is recorded: proven from inside the messenger, or offered by a
// bot to the account and accepted by the signed-in user.
const (
	MethodPairing = "pairing"
	MethodOffer   = "offer"
)

const unnamedAccount = "your AgentArea account"

var _ api.MessengerLinks = (*Service)(nil)

// Holder is the user a live messenger account is linked to.
func (s *Service) Holder(ctx context.Context, provider, externalID string) (string, bool, error) {
	q, release, err := s.d.DB.Global().Read(ctx)
	if err != nil {
		return "", false, err
	}
	defer release()
	return s.d.Store.ExternalIdentityHolder(ctx, q, provider, externalID)
}

// Accounts are the user's live accounts of provider, the most recently linked first.
func (s *Service) Accounts(ctx context.Context, userID, provider string) ([]string, error) {
	q, release, err := s.d.DB.Global().Read(ctx)
	if err != nil {
		return nil, err
	}
	defer release()
	return s.d.Store.LinkedExternalIDs(ctx, q, userID, provider)
}

// Redeem spends a link code from the messenger account.
func (s *Service) Redeem(ctx context.Context, code, provider, externalID string) (string, bool, error) {
	if s.d.LinkCodes == nil {
		return "", false, domain.ErrLinkingNeedsRedis
	}
	if code == "" {
		return "", false, nil
	}
	return s.d.LinkCodes.Redeem(ctx, code, provider, externalID)
}

// Confirm links the account to the user it redeemed a code for; linking it
// again to the same user only keeps how the messenger names it now.
func (s *Service) Confirm(ctx context.Context, account api.Account) (string, bool, error) {
	if s.d.LinkCodes == nil {
		return "", false, domain.ErrLinkingNeedsRedis
	}
	userID, ok, err := s.d.LinkCodes.Confirm(ctx, account.Provider, account.ExternalID)
	if err != nil || !ok {
		return "", false, err
	}
	if _, err := s.link(ctx, userID, messengerAccount(account), MethodPairing); err != nil {
		return "", false, err
	}
	return userID, true, nil
}

// Offer issues the code a bot hands an unlinked sender.
func (s *Service) Offer(ctx context.Context, account api.Account, bot api.OfferingBot) (string, bool, error) {
	if s.d.LinkCodes == nil {
		return "", false, domain.ErrLinkingNeedsRedis
	}
	return s.d.LinkCodes.Offer(ctx, domain.LinkOffer{MessengerAccount: messengerAccount(account),
		WorkspaceID: bot.WorkspaceID, SourceID: bot.SourceID, Bot: bot.Username}, api.OfferTTL)
}

// link links the account to userID, or renames it when userID already holds
// it; api.ErrAccountTaken when another user does.
func (s *Service) link(ctx context.Context, userID string, a domain.MessengerAccount, method string) (domain.ExternalIdentity, error) {
	var out domain.ExternalIdentity
	link := func() error {
		return s.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
			holder, held, err := s.d.Store.ExternalIdentityHolder(ctx, q, a.Provider, a.ExternalID)
			if err != nil {
				return err
			}
			if held {
				if holder != userID {
					return api.ErrAccountTaken
				}
				out, err = s.d.Store.RenameExternalIdentity(ctx, q, userID, a, s.local())
				return err
			}
			out, err = s.d.Store.InsertExternalIdentity(ctx, q, userID, a, method, s.local())
			return err
		})
	}
	err := link()
	if isUniqueViolation(err) {
		err = link()
	}
	if err != nil {
		return domain.ExternalIdentity{}, err
	}
	s.log.InfoContext(ctx, "Messenger account linked", "provider", a.Provider, "user_id", userID)
	return out, nil
}

// nameLimit is the width of user_external_identities' username and display_name.
const nameLimit = 255

func messengerAccount(a api.Account) domain.MessengerAccount {
	return domain.MessengerAccount{Provider: a.Provider, ExternalID: a.ExternalID,
		Username: clip(strings.TrimPrefix(strings.TrimSpace(a.Username), "@")), Name: clip(strings.TrimSpace(a.Name))}
}

func clip(s string) string {
	if r := []rune(s); len(r) > nameLimit {
		return string(r[:nameLimit])
	}
	return s
}

// Describe is the user's masked email.
func (s *Service) Describe(ctx context.Context, userID string) string {
	if s.d.Directory == nil {
		return unnamedAccount
	}
	who, err := s.d.Directory.Lookup(ctx, userID)
	if err != nil {
		s.log.WarnContext(ctx, "Identity directory unavailable; not naming the account", "error", err.Error())
		return unnamedAccount
	}
	if who == nil || who.Email == nil {
		return unnamedAccount
	}
	return MaskEmail(*who.Email)
}

// MaskEmail keeps the first letter of the local part and the domain.
func MaskEmail(email string) string {
	local, domainPart, found := strings.Cut(email, "@")
	if !found || domainPart == "" {
		return unnamedAccount
	}
	first := ""
	for _, r := range local {
		first = string(r)
		break
	}
	return first + "***@" + domainPart
}
