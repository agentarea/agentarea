package connections

import (
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/service"
)

// CatalogUses is what a catalog sync does to connections made from its items.
func (m *Module) CatalogUses() api.CatalogUses { return service.CatalogUses{} }
