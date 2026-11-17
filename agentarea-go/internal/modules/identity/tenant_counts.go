package identity

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/store"
)

// TenantCounts reads identity's counts over every tenant workspace.
func (m *Module) TenantCounts() api.TenantCounter { return store.TenantReads{DB: m.d.DB} }
