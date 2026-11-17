package streams

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store"
)

// TenantCounts reads streams counts over every tenant workspace.
func (m *Module) TenantCounts() api.TenantCounter { return store.TenantReads{DB: m.d.DB} }
