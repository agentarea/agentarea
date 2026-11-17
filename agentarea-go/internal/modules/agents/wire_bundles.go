package agents

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
)

// Bundles is what a bundle deploy reads and writes of agents and skills; nil without a full graph.
func (m *Module) Bundles() catalogapi.BundleAgents {
	if m.svc == nil {
		return nil
	}
	return service.BundleAgents{K: m.skills()}
}
