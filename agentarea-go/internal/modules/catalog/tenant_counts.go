package catalog

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/store"
)

// TenantCounts reads the catalog's slugs and the tenant installed bundles.
func (m *Module) TenantCounts() api.TenantCounter { return store.TenantReads{DB: m.d.DB} }
