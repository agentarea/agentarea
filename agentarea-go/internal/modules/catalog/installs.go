package catalog

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
)

// Installs is what agents reads and writes of the catalog to install its agents and skills.
func (m *Module) Installs() api.Installs {
	return m.svc.Installs()
}
