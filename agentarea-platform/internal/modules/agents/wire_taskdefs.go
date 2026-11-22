package agents

import (
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/handlers"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/service"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

// TaskDefDeps are the ports only the task definition routes need.
type TaskDefDeps struct {
	// TaskDefTriggers counts the triggers that run a saved task (streams); nil answers 501
	// for DELETE and for a PUT that changes the agent.
	TaskDefTriggers service.TaskDefTriggers
	// TaskDefRunner starts a run of a saved task (runs); nil answers 501 for POST .../run.
	TaskDefRunner service.TaskDefRunner
}

func (m *Module) taskDefs() *service.TaskDefs {
	return service.NewTaskDefs(m.svc, service.TaskDefPorts{Triggers: m.d.TaskDefTriggers, Runner: m.d.TaskDefRunner})
}

// TaskBundles is what a bundle deploy reads and writes of saved tasks; nil without a full graph.
func (m *Module) TaskBundles() catalogapi.BundleTasks {
	if m.svc == nil {
		return nil
	}
	return service.BundleTasks{X: m.taskDefs()}
}

// TaskDefsToolset is what the platform MCP task_definitions toolset calls; nil without a full graph.
func (m *Module) TaskDefsToolset() api.TaskDefs {
	if m.svc == nil {
		return nil
	}
	return handlers.TaskDefsToolset{Svc: m.svc, TaskDefs: m.taskDefs()}
}
