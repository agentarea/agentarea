package agents

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
)

// AgentTools is what connections reads of agents' saved tools.
func (m *Module) AgentTools() api.AgentTools { return service.AgentTools{DB: m.d.DB} }

// ClientBundles is what connections reads of clients; nil without a full graph.
func (m *Module) ClientBundles() api.ClientBundles {
	if m.svc == nil {
		return nil
	}
	return service.ClientBundles{Skills: m.skills()}
}
