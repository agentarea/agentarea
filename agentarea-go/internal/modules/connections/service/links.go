package service

import (
	"context"
	"crypto/rand"
	"encoding/base64"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
)

// newToken is secrets.token_urlsafe(LINK_TOKEN_BYTES).
func newToken() (string, error) {
	b := make([]byte, domain.LinkTokenBytes)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}

// CreateLink makes a link for a container instance the workspace sees.
func (s *Service) CreateLink(ctx context.Context, c authn.Caller, inst uuid.UUID, access string,
	provider map[string]any, days *int) (domain.OAuthLink, error) {
	token, err := newToken()
	if err != nil {
		return domain.OAuthLink{}, err
	}
	var out domain.OAuthLink
	err = s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		_, ok, err := s.d.Instances.Get(ctx, sess, inst)
		if err != nil {
			return err
		}
		if !ok {
			return &domain.NotFound{Msg: "MCP instance " + inst.String() + " not found"}
		}
		if err := domain.CheckAccessControl(access); err != nil {
			return err
		}
		now := s.d.Now()
		l, err := s.d.Links.Insert(ctx, sess, s.d.NewID(), c.UserID, inst, token, access, provider,
			domain.LinkExpiry(now, days), now)
		if err != nil {
			return err
		}
		out = l
		return nil
	})
	return out, err
}

// ListLinks is the links of an instance; an instance the workspace does not
// have has none.
func (s *Service) ListLinks(ctx context.Context, c authn.Caller, inst uuid.UUID) ([]domain.OAuthLink, error) {
	var out []domain.OAuthLink
	err := s.read(ctx, c, func(sess db.Session) (err error) {
		out, err = s.d.Links.List(ctx, sess, inst)
		return err
	})
	return out, err
}

// GetLink is the link id, 404 when the workspace has none.
func (s *Service) GetLink(ctx context.Context, c authn.Caller, id uuid.UUID) (domain.OAuthLink, error) {
	var out domain.OAuthLink
	err := s.read(ctx, c, func(sess db.Session) error {
		l, ok, err := s.d.Links.Get(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return domain.ErrLinkNotFound()
		}
		out = l
		return nil
	})
	return out, err
}

// RevokeLink turns a link off; 404 when the workspace has none.
func (s *Service) RevokeLink(ctx context.Context, c authn.Caller, id uuid.UUID) error {
	return s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		ok, err := s.d.Links.Deactivate(ctx, sess, id, s.d.Now())
		if err != nil {
			return err
		}
		if !ok {
			return domain.ErrLinkNotFound()
		}
		return nil
	})
}
