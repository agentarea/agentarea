package service

import (
	"context"
	"errors"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
)

const telegram = "telegram"

// StartTelegramLink issues a link code for the caller; the scope check ran
// at the route.
func (s *Service) StartTelegramLink(ctx context.Context, p authn.Principal) (string, error) {
	if s.d.LinkCodes == nil {
		return "", domain.ErrLinkingNeedsRedis
	}
	return s.d.LinkCodes.Issue(ctx, p.UserID)
}

// TelegramOffer is the Telegram account a bot offered code for, and who
// already holds it: "", domain.OfferHeldByYou or domain.OfferHeldByAnother.
func (s *Service) TelegramOffer(ctx context.Context, p authn.Principal, code string) (domain.LinkOffer, string, error) {
	if s.d.LinkCodes == nil {
		return domain.LinkOffer{}, "", domain.ErrLinkingNeedsRedis
	}
	o, ok, err := s.d.LinkCodes.PeekOffer(ctx, code)
	if err != nil {
		return domain.LinkOffer{}, "", err
	}
	if !ok || o.Provider != telegram {
		return domain.LinkOffer{}, "", domain.ErrLinkOfferGone
	}
	q, release, err := s.d.DB.Global().Read(ctx)
	if err != nil {
		return domain.LinkOffer{}, "", err
	}
	defer release()
	holder, held, err := s.d.Store.ExternalIdentityHolder(ctx, q, o.Provider, o.ExternalID)
	switch {
	case err != nil:
		return domain.LinkOffer{}, "", err
	case !held:
		return o, "", nil
	case holder == p.UserID:
		return o, domain.OfferHeldByYou, nil
	}
	return o, domain.OfferHeldByAnother, nil
}

// AcceptTelegramOffer spends code and links the Telegram account it was
// offered to to the caller, who confirmed it; the scope check ran at the route.
func (s *Service) AcceptTelegramOffer(ctx context.Context, p authn.Principal, code string) (domain.ExternalIdentity, error) {
	if s.d.LinkCodes == nil {
		return domain.ExternalIdentity{}, domain.ErrLinkingNeedsRedis
	}
	o, ok, err := s.d.LinkCodes.TakeOffer(ctx, code)
	if err != nil {
		return domain.ExternalIdentity{}, err
	}
	if !ok || o.Provider != telegram {
		return domain.ExternalIdentity{}, domain.ErrLinkOfferGone
	}
	link, err := s.link(ctx, p.UserID, o.MessengerAccount, MethodOffer)
	if errors.Is(err, api.ErrAccountTaken) {
		return domain.ExternalIdentity{}, domain.ErrMessengerAccountTaken
	}
	return link, err
}

// ListExternalIdentities is the caller's live links, oldest first.
func (s *Service) ListExternalIdentities(ctx context.Context, p authn.Principal) ([]domain.ExternalIdentity, error) {
	q, release, err := s.d.DB.Global().Read(ctx)
	if err != nil {
		return nil, err
	}
	defer release()
	return s.d.Store.ListExternalIdentities(ctx, q, p.UserID)
}

// UnlinkExternalIdentity revokes one of the caller's live links.
func (s *Service) UnlinkExternalIdentity(ctx context.Context, p authn.Principal, id uuid.UUID) error {
	return s.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		ok, err := s.d.Store.RevokeExternalIdentity(ctx, q, p.UserID, id, s.local())
		if err != nil {
			return err
		}
		if !ok {
			return domain.ErrLinkNotFound
		}
		return nil
	})
}
