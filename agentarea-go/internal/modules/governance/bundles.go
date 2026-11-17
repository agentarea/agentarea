package governance

import (
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/service"
)

// Bundles is what a bundle deploy reads and writes of governance rules.
func (m *Module) Bundles() catalogapi.BundleRules { return service.BundleRules{S: m.svc} }
