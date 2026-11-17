package streams

import (
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/handlers"
)

// AgentTriggers is what agent creation calls to check and make the triggers sent with a new agent.
func (m *Module) AgentTriggers() api.AgentTriggers { return handlers.NewAgentTriggers(m.svc, m.d.Log) }
