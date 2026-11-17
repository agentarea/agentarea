package service

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
)

// StartTelegramLink issues a link code for the caller; the scope check ran
// at the route.
func (s *Service) StartTelegramLink(ctx context.Context, p authn.Principal) (string, error) {
	if s.d.LinkCodes == nil {
		return "", domain.ErrLinkingNeedsRedis
	}
	return s.d.LinkCodes.Issue(ctx, p.UserID)
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
