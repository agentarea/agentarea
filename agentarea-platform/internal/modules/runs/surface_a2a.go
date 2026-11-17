package runs

import agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"

// A2A is what the A2A task methods of agents run on.
func (m *Surface) A2A() agentsapi.A2ARuns { return m.s.A2A() }
