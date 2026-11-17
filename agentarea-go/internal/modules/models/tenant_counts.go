package models

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/store"
)

// TenantCounts reads models counts over every tenant workspace.
func (m *Module) TenantCounts() api.TenantCounter { return store.TenantReads{DB: m.d.DB} }
