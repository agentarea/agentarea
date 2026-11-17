package agents

import "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"

// Standing is an agent's status and its saved tasks, read without a caller.
func (m *Module) Standing() api.Standing { return m.lookup }
