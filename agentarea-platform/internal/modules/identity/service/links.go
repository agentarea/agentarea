package service

import (
	"context"
	"errors"
	"fmt"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
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

// TelegramOfferView is the Telegram account a bot offered a code for, the
// workspace whose bot offered it, and who already holds the account: "",
// domain.OfferHeldByYou or domain.OfferHeldByAnother.
type TelegramOfferView struct {
	Offer         domain.LinkOffer
	WorkspaceName string
	LinkedTo      string
}

// TelegramOffer shows the caller, a member of the bot's workspace, what code links.
func (s *Service) TelegramOffer(ctx context.Context, p authn.Principal, code string) (TelegramOfferView, error) {
	o, w, err := s.telegramOffer(ctx, p, code)
	if err != nil {
		return TelegramOfferView{}, err
	}
	q, release, err := s.d.DB.Global().Read(ctx)
	if err != nil {
		return TelegramOfferView{}, err
	}
	defer release()
	v := TelegramOfferView{Offer: o, WorkspaceName: w.Name}
	holder, held, err := s.d.Store.ExternalIdentityHolder(ctx, q, o.Provider, o.ExternalID)
	switch {
	case err != nil:
		return TelegramOfferView{}, err
	case !held:
	case holder == p.UserID:
		v.LinkedTo = domain.OfferHeldByYou
	default:
		v.LinkedTo = domain.OfferHeldByAnother
	}
	return v, nil
}

// telegramOffer is the live Telegram offer code names and the workspace whose
// bot made it, refused unless the caller owns or is a member of that workspace:
// a code someone else got from a bot links nothing for a stranger to it.
func (s *Service) telegramOffer(ctx context.Context, p authn.Principal, code string) (domain.LinkOffer, domain.Workspace, error) {
	if s.d.LinkCodes == nil {
		return domain.LinkOffer{}, domain.Workspace{}, domain.ErrLinkingNeedsRedis
	}
	o, ok, err := s.d.LinkCodes.PeekOffer(ctx, code)
	if err != nil {
		return domain.LinkOffer{}, domain.Workspace{}, err
	}
	if !ok || o.Provider != telegram || o.WorkspaceID == "" {
		return domain.LinkOffer{}, domain.Workspace{}, domain.ErrLinkOfferGone
	}
	q, release, err := s.d.DB.Global().Read(ctx)
	if err != nil {
		return domain.LinkOffer{}, domain.Workspace{}, err
	}
	w, found, err := s.d.Store.GetWorkspace(ctx, q, o.WorkspaceID)
	release()
	if err != nil {
		return domain.LinkOffer{}, domain.Workspace{}, err
	}
	if !found {
		return domain.LinkOffer{}, domain.Workspace{}, domain.ErrLinkOfferGone
	}
	if w.OwnerUserID == p.UserID {
		return o, w, nil
	}
	if s.d.Reader == nil {
		return domain.LinkOffer{}, domain.Workspace{}, fmt.Errorf("%w: no graph reader", domain.ErrMembershipGraphDown)
	}
	member, err := authz.IsWorkspaceMember(ctx, s.d.Reader, w.ID, p.UserID)
	if err != nil {
		return domain.LinkOffer{}, domain.Workspace{}, err
	}
	if !member {
		return domain.LinkOffer{}, domain.Workspace{}, domain.ErrLinkOfferForeign
	}
	return o, w, nil
}

// AcceptTelegramOffer spends code and links the Telegram account it was
// offered to to the caller, a member of the bot's workspace who confirmed it;
// the scope check ran at the route. A refused caller leaves the code unspent.
func (s *Service) AcceptTelegramOffer(ctx context.Context, p authn.Principal, code string) (domain.ExternalIdentity, error) {
	if _, _, err := s.telegramOffer(ctx, p, code); err != nil {
		return domain.ExternalIdentity{}, err
	}
	o, ok, err := s.d.LinkCodes.TakeOffer(ctx, code)
	if err != nil {
		return domain.ExternalIdentity{}, err
	}
	if !ok {
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
