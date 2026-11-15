package runs

import "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"

// PlatformRuns is what the platform runs toolset calls.
func (m *Surface) PlatformRuns() api.PlatformRuns { return m.s.PlatformRuns() }

// PlatformInbox is what the platform inbox toolset calls.
func (m *Surface) PlatformInbox() api.PlatformInbox { return m.s.PlatformInbox() }
