package service

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/domain"
)

// ListAPIKeys is list_api_keys: an admin sees the workspace's keys, anyone
// else the keys they created; a runner's key is never listed here.
func (s *Service) ListAPIKeys(ctx context.Context, c authn.Caller, admin bool, agentID *uuid.UUID) ([]domain.APIKey, error) {
	var createdBy *string
	if !admin {
		createdBy = &c.UserID
	}
	sess, release, err := s.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return nil, err
	}
	defer release()
	keys, err := s.d.Store.ListAPIKeys(ctx, sess, createdBy, agentID)
	if err != nil {
		return nil, err
	}
	out := make([]domain.APIKey, 0, len(keys))
	for _, k := range keys {
		if k.ClientID == nil {
			out = append(out, k)
		}
	}
	return out, nil
}

// GetAPIKey is get_api_key: someone else's key is as missing as an absent
// one to a member, and a runner's key to everyone.
func (s *Service) GetAPIKey(ctx context.Context, c authn.Caller, isAdmin func() (bool, error), id uuid.UUID) (domain.APIKey, error) {
	sess, release, err := s.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return domain.APIKey{}, err
	}
	k, ok, err := s.d.Store.APIKeyByID(ctx, sess, id)
	release()
	if err != nil {
		return domain.APIKey{}, err
	}
	if !ok || k.ClientID != nil {
		return domain.APIKey{}, domain.ErrAPIKeyNotFound
	}
	if k.CreatedBy != c.UserID {
		admin, err := isAdmin()
		if err != nil {
			return domain.APIKey{}, err
		}
		if !admin {
			return domain.APIKey{}, domain.ErrAPIKeyNotFound
		}
	}
	return k, nil
}

// RevokeAPIKey is revoke_api_key after the scope check: the key's creator,
// else an admin (requireAdmin answers 403 to anyone else).
func (s *Service) RevokeAPIKey(ctx context.Context, c authn.Caller, requireAdmin func() error, id uuid.UUID) error {
	sess, release, err := s.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return err
	}
	k, ok, err := s.d.Store.APIKeyByID(ctx, sess, id)
	release()
	if err != nil {
		return err
	}
	if !ok || k.ClientID != nil {
		return domain.ErrAPIKeyNotFound
	}
	if k.CreatedBy != c.UserID {
		if err := requireAdmin(); err != nil {
			return err
		}
	}
	err = s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		_, ok, err := s.d.Store.APIKeyByID(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return domain.ErrAPIKeyNotFound
		}
		return s.d.Store.DeactivateAPIKey(ctx, sess, id, s.local())
	})
	if err != nil {
		return err
	}
	return s.audit(ctx, c, "api_key.revoke", "api_key", id.String(), map[string]any{"resource_name": k.Name, "token_prefix": k.TokenPrefix})
}
