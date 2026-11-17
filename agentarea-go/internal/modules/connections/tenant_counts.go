package connections

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/store"
)

// TenantCounts reads connections counts over every tenant workspace.
func (m *Module) TenantCounts() api.TenantCounter { return store.TenantReads{DB: m.d.DB} }
