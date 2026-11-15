package streams

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/service"
)

// TriggerBoard is the broken and the scheduled triggers the dashboard and the agent overview show.
func (m *Module) TriggerBoard() api.TriggerBoard { return service.TriggerBoard{DB: m.d.DB} }
