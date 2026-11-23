package streams

import (
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/handlers"
)

// PlatformTriggers is what the platform triggers toolset calls.
func (m *Module) PlatformTriggers() api.PlatformTriggers { return handlers.NewPlatformTriggers(m.svc) }

// PlatformStreams is what the platform streams toolset calls.
func (m *Module) PlatformStreams() api.PlatformStreams {
	return handlers.NewPlatformStreams(m.svc, m.d.Log)
}

// PlatformStreamEvents is what the platform stream_events toolset calls.
func (m *Module) PlatformStreamEvents() api.PlatformStreamEvents {
	return handlers.NewPlatformStreamEvents(m.svc)
}

// PlatformMessages is what the platform messages toolset calls.
func (m *Module) PlatformMessages() api.PlatformMessages { return handlers.NewPlatformMessages(m.svc) }
