package agents

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/store"
)

// TenantCounts reads agents counts over every tenant workspace.
func (m *Module) TenantCounts() api.TenantCounter { return store.TenantReads{DB: m.d.DB} }
