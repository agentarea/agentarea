package agents

import "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"

// Standing is an agent's status and its saved tasks, read without a caller.
func (m *Module) Standing() api.Standing { return m.lookup }
