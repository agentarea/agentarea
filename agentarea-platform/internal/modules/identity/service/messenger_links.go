package service

import (
	"context"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
)

// MethodPairing is how a link proven from inside the messenger is recorded.
const MethodPairing = "pairing"

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
// again to the same user changes nothing.
func (s *Service) Confirm(ctx context.Context, provider, externalID string) (string, bool, error) {
	if s.d.LinkCodes == nil {
		return "", false, domain.ErrLinkingNeedsRedis
	}
	userID, ok, err := s.d.LinkCodes.Confirm(ctx, provider, externalID)
	if err != nil || !ok {
		return "", false, err
	}
	link := func() error {
		return s.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
			holder, held, err := s.d.Store.ExternalIdentityHolder(ctx, q, provider, externalID)
			if err != nil {
				return err
			}
			if held {
				if holder != userID {
					return api.ErrAccountTaken
				}
				return nil
			}
			_, err = s.d.Store.InsertExternalIdentity(ctx, q, userID, provider, externalID, MethodPairing, s.local())
			return err
		})
	}
	err = link()
	if isUniqueViolation(err) {
		err = link()
	}
	if err != nil {
		return "", false, err
	}
	s.log.InfoContext(ctx, "Messenger account linked", "provider", provider, "user_id", userID)
	return userID, true, nil
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
