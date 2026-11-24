package runs

import "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"

// TaskOutcomes is what the consumers of task events read of a task.
func (m *Surface) TaskOutcomes() api.TaskOutcomes { return m.s }
