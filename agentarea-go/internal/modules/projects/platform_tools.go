package projects

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/projects/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/projects/handlers"
)

// PlatformProjects is what the platform projects toolset calls.
func (m *Module) PlatformProjects() api.PlatformProjects { return handlers.PlatformTools{Svc: m.svc} }
