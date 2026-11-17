package agents

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/service"
)

// AgentTools is what connections reads of agents' saved tools.
func (m *Module) AgentTools() api.AgentTools { return service.AgentTools{DB: m.d.DB} }

// ClientBundles is what connections reads of clients; nil without a full graph.
// connections takes it before Use, so it reads the skill ports at call time.
func (m *Module) ClientBundles() api.ClientBundles {
	if m.svc == nil {
		return nil
	}
	return lateClientBundles{m: m}
}

type lateClientBundles struct{ m *Module }

func (l lateClientBundles) Locate(ctx context.Context, clientID string, workspaces []string) (string, bool, error) {
	return service.ClientBundles{Skills: l.m.skills()}.Locate(ctx, clientID, workspaces)
}

func (l lateClientBundles) Bundle(ctx context.Context, ws scope.Workspace, userID, clientID string) (api.ClientBundle, bool, error) {
	return service.ClientBundles{Skills: l.m.skills()}.Bundle(ctx, ws, userID, clientID)
}
