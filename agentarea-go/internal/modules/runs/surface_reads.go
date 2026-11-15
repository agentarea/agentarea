package runs

import "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"

// TaskReads is the task statuses and costs other modules show.
func (m *Surface) TaskReads() api.TaskReads { return m.s }

// FiringTasks is what a trigger firing reads and restarts of its tasks.
func (m *Surface) FiringTasks() api.FiringTasks { return m.s }
