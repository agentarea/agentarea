package streams

import (
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/service"
)

// Bundles is what a bundle deploy reads and writes of triggers and channel streams.
func (m *Module) Bundles() catalogapi.BundleTriggers { return service.BundleTriggers{S: m.svc} }
