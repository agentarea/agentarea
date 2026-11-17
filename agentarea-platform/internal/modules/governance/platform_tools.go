package governance

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/handlers"
)

// PlatformPolicies is what the platform policies toolset calls.
func (m *Module) PlatformPolicies() api.PlatformPolicies { return m.platformTools() }

// PlatformSecrets is what the platform secrets toolset calls; nil without the secrets profile.
func (m *Module) PlatformSecrets() api.PlatformSecrets {
	if !m.svc.SecretsMounted() {
		return nil
	}
	return m.platformTools()
}

// PlatformAudit is what the platform audit toolset calls.
func (m *Module) PlatformAudit() api.PlatformAudit { return m.platformTools() }

func (m *Module) platformTools() handlers.PlatformTools {
	return handlers.PlatformTools{Svc: m.svc, Admin: func(ctx context.Context, c authn.Caller) error {
		if m.d.Admin == nil {
			return authz.ErrNotWorkspaceAdmin
		}
		return m.d.Admin(authn.WithCaller(ctx, c))
	}}
}
