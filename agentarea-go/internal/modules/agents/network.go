package agents

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
)

// Network is the agents and skills the network graph, its people access and the dashboard read.
func (m *Module) Network() api.Network { return service.Network{DB: m.d.DB} }
