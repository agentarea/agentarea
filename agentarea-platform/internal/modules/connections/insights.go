package connections

import (
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/service"
)

// ConnectionBoard is the MCP instances and OpenAPI connections the dashboard and the network graph show.
func (m *Module) ConnectionBoard() api.ConnectionBoard { return service.ConnectionBoard{DB: m.d.DB} }
