package governance

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/store"
)

// TenantCounts reads governance counts over every tenant workspace.
func (m *Module) TenantCounts() api.TenantCounter { return store.TenantReads{DB: m.d.DB} }
