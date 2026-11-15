package agents

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
)

// RunnerClients is what the runner socket reads and writes of clients; nil without a full graph.
func (m *Module) RunnerClients() api.RunnerClients {
	if m.svc == nil {
		return nil
	}
	return service.RunnerClients{K: m.skills()}
}
