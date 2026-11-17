package runs

import "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"

// DefinitionRuns is what a task definition's run starts a task through.
func (m *Surface) DefinitionRuns() api.DefinitionRuns { return m.s }
