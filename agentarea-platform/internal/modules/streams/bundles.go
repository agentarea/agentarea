package streams

import (
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
)

// Bundles is what a bundle deploy reads and writes of triggers and channel streams.
func (m *Module) Bundles() catalogapi.BundleTriggers { return service.BundleTriggers{S: m.svc} }

// StreamBundles is what a bundle deploy reads and writes of streams.
func (m *Module) StreamBundles() catalogapi.BundleStreams { return service.BundleStreams{S: m.svc} }
