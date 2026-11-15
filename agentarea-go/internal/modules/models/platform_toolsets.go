package models

import (
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/handlers"
)

// PlatformProviders is what the platform providers toolset calls; specs
// lists the provider specs (catalog's SpecLists).
func (m *Module) PlatformProviders(specs catalogapi.SpecLists) api.PlatformProviders {
	return handlers.ProvidersToolset{Svc: m.svc, Specs: specs}
}

// PlatformModels is what the platform models toolset calls; specs lists the
// model specs (catalog's SpecLists).
func (m *Module) PlatformModels(specs catalogapi.SpecLists) api.PlatformModels {
	return handlers.ModelsToolset{Svc: m.svc, Specs: specs}
}
