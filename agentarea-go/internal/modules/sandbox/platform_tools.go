package sandbox

import "github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"

// PlatformFiles is what the platform workspace_files toolset calls.
func (m *Module) PlatformFiles() api.PlatformFiles { return m.svc.PlatformFiles() }
