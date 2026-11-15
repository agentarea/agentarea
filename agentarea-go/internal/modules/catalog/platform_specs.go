package catalog

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/service"
)

// SpecLists lists the provider and model specs a workspace sees (the
// providers and models platform toolsets).
func (m *Module) SpecLists() api.SpecLists { return service.SpecLists{S: m.svc} }
