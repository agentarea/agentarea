package app

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	agentsservice "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/secrets"
)

// a2aPushSecrets keeps an A2A push config's callback token in the workspace secret store.
type a2aPushSecrets struct {
	db db.Database
	f  *secrets.Factory
}

var _ agentsservice.A2APushSecrets = a2aPushSecrets{}

func (p a2aPushSecrets) Set(ctx context.Context, c authn.Caller, name, value string) error {
	return p.db.Write(ctx, c.Workspace, func(ctx context.Context, tx db.Session) error {
		return p.f.Manager(tx, c.UserID).Set(ctx, name, value)
	})
}

func (p a2aPushSecrets) Delete(ctx context.Context, c authn.Caller, name string) error {
	return p.db.Write(ctx, c.Workspace, func(ctx context.Context, tx db.Session) error {
		_, err := p.f.Manager(tx, c.UserID).Delete(ctx, name)
		return err
	})
}
