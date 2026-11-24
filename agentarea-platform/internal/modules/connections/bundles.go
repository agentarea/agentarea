package connections

import (
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/service"
)

// Bundles is what a bundle deploy reads and writes of MCP connections.
func (m *Module) Bundles() catalogapi.BundleMCPs {
	return service.BundleMCPs{S: func() *service.Service { return m.svc }}
}

// OpenAPIBundles is what a bundle deploy reads and writes of OpenAPI connections.
func (m *Module) OpenAPIBundles() catalogapi.BundleOpenAPIs {
	return service.BundleOpenAPIs{S: func() *service.Service { return m.svc }}
}
