package service

import (
	"context"
	"errors"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
)

// GetAuthConfigForUse is MCPAuthService.get_for_use inside sess: only the
// config's creator or a workspace admin may attach it to a connection. An
// agent acts as itself, so it may only when the config was lent to it.
func (s *Service) GetAuthConfigForUse(ctx context.Context, sess db.Session, c authn.Caller, id uuid.UUID) (domain.AuthConfig, error) {
	a, ok, err := s.d.Auth.Get(ctx, sess, id)
	if err != nil {
		return domain.AuthConfig{}, err
	}
	if !ok {
		return domain.AuthConfig{}, &domain.Invalid{Msg: "Auth config " + id.String() + " not found in this workspace"}
	}
	if c.ActsAsAgent() {
		if s.d.Graph == nil {
			return domain.AuthConfig{}, errors.New("an agent using an auth config needs the authorization graph")
		}
		lent, err := s.perms.Check(ctx, c.GraphSubject(), "use_connection", "mcp_auth_config", a.ID)
		if err != nil {
			return domain.AuthConfig{}, err
		}
		if !lent {
			return domain.AuthConfig{}, &domain.Forbidden{Msg: "Auth config " + id.String() + " was not lent to this agent."}
		}
		return a, nil
	}
	if a.CreatedBy == c.UserID {
		return a, nil
	}
	if s.d.Admin != nil {
		err := s.d.Admin(authn.WithCaller(ctx, c))
		if err == nil {
			return a, nil
		}
		if !errors.Is(err, authz.ErrNotWorkspaceAdmin) {
			return domain.AuthConfig{}, err
		}
	}
	return domain.AuthConfig{}, &domain.Forbidden{Msg: "Auth config " + id.String() + " can only be used by its creator or a workspace admin."}
}
