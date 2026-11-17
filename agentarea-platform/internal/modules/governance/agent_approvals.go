package governance

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/service"
)

// AgentApprovals is the agent editor's approval toggle as policy rules.
func (m *Module) AgentApprovals() api.AgentApprovals {
	return agentApprovals{svc: m.svc, admin: m.d.Admin}
}

// InstallPolicy is the catalog install guard.
func (m *Module) InstallPolicy() api.InstallPolicy { return installPolicy{svc: m.svc} }

type agentApprovals struct {
	svc   *service.Service
	admin func(context.Context) error
}

func (a agentApprovals) Targets(ctx context.Context, ws scope.Workspace, agentIDs []string) (map[string][]string, error) {
	return a.svc.Targets(ctx, ws, agentIDs)
}

func (a agentApprovals) Sync(ctx context.Context, s db.Session, c authn.Caller, agentID string, targets []string) error {
	return a.svc.SyncAgentApprovals(ctx, s, c, agentID, targets)
}

func (a agentApprovals) Release(ctx context.Context, s db.Session, c authn.Caller, agentID string, unticked []string) error {
	return a.svc.ReleaseAgentApprovals(ctx, s, agentID, unticked, a.admin)
}

type installPolicy struct{ svc *service.Service }

func (p installPolicy) RequireAllowed(ctx context.Context, c authn.Caller, registryID, trust string) error {
	return p.svc.RequireInstallAllowed(ctx, c, registryID, trust)
}

func (p installPolicy) RunRefusal(ctx context.Context, ws scope.Workspace, registryID, trust string) (string, bool, error) {
	return p.svc.RunRefusal(ctx, ws, registryID, trust)
}
