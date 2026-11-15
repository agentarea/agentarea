package governance

import "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"

// SpendCaps is the workspace monthly spend cap the settings and the dashboard read and set.
func (m *Module) SpendCaps() api.SpendCaps { return m.svc }
