package runs

import (
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
)

// TenantCounts reads runs' counts over every tenant workspace.
func (m *Surface) TenantCounts() api.TenantCounter { return store.TenantReads{DB: m.d.Service.DB} }
