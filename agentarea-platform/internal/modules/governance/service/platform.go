package service

import (
	"context"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/store"
)

var _ api.EgressExitDeclarations = (*Service)(nil)

// DeclareEgressExit implements api.EgressExitDeclarations in the platform workspace.
func (s *Service) DeclareEgressExit(ctx context.Context, e api.DeclaredEgressExit) error {
	ws, err := scope.NewWorkspace("platform", "")
	if err != nil {
		return err
	}
	return s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		return store.DeclareEgressExit(ctx, sess, e, "platform", time.Now())
	})
}
