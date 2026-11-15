// Package runs is the runs module: tasks and runs: the agent loop, task events, conversation, approvals, cost entries, the runner.
package runs

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/lifecycle"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/workflows"
)

// Deps are what runs needs from other modules and the kernel, as interfaces
// declared in its service/deps.go; app passes them in (rule 2).
type Deps struct {
	Service service.Deps
	// Executor signals a run from its runner turn activity and starts the
	// runs of tasks left unstarted.
	Executor durable.Executor
	// AgentQueue is AGENTAREA_TEMPORAL_QUEUE, where runs are started.
	AgentQueue string
	// Scheduling are the ports of the reconciler, the cron sync and the
	// trigger activities; a nil Launcher is the agent queue's launcher over Executor.
	Scheduling service.SchedulingDeps
}

// Module is runs, constructed once per process; a role picks which of its
// parts run.
type Module struct {
	d          Deps
	activities *workflows.Activities
	schedule   *workflows.ScheduleActivities
	svc        *service.Service
}

// New constructs the module.
func New(d Deps) *Module {
	if d.Scheduling.Launcher == nil && d.Executor != nil && d.AgentQueue != "" {
		d.Scheduling.Launcher = workflows.Launcher{Exec: d.Executor, Queue: d.AgentQueue, Now: d.Service.Now}
	}
	if d.Scheduling.DB == nil {
		d.Scheduling.DB = d.Service.DB
	}
	if d.Scheduling.Log == nil {
		d.Scheduling.Log = d.Service.Log
	}
	svc := service.New(d.Service)
	return &Module{
		d:          d,
		svc:        svc,
		activities: workflows.NewActivities(svc, d.Executor),
		schedule:   workflows.NewScheduleActivities(service.NewScheduling(d.Scheduling)),
	}
}

// Name is the module's name in the role table.
func (*Module) Name() string { return "runs" }

// Register registers the agent queue's part on a worker: the agent workflow
// and its activities (steps 1-12), and the reconciler (step 13).
func (m *Module) Register(w durable.Worker) {
	for _, f := range workflows.AgentQueueWorkflows() {
		w.RegisterWorkflow(f)
	}
	workflows.RegisterActivities(w, m.activities)
	workflows.RegisterScheduleActivities(w, m.schedule, workflows.QueueAgent)
}

// RegisterTriggers registers the trigger queue's part: cron and stream
// trigger firings and the cron schedule sync (steps 13-14).
func (m *Module) RegisterTriggers(w durable.Worker) {
	for _, f := range workflows.TriggerQueueWorkflows() {
		w.RegisterWorkflow(f)
	}
	workflows.RegisterScheduleActivities(w, m.schedule, workflows.QueueTrigger)
}

// AgentActivities and TriggerActivities are the activities each queue must have registered.
func (*Module) AgentActivities() []string   { return workflows.QueueActivities(workflows.QueueAgent) }
func (*Module) TriggerActivities() []string { return workflows.QueueActivities(workflows.QueueTrigger) }

// Schedules are the Temporal Schedules the worker keeps: the reconciler on
// the agent queue and the cron sync on the trigger queue.
func (m *Module) Schedules() []durable.Schedule {
	return []durable.Schedule{api.UndispatchedTasksSchedule(m.d.AgentQueue), api.CronSyncSchedule(m.d.Scheduling.TriggerQueue)}
}

// Missing names the ports a worker that runs every workflow lacks.
func (m *Module) Missing() []string {
	s := m.d.Service
	var out []string
	for _, p := range []struct {
		name string
		nil  bool
	}{
		{"database", s.DB == nil}, {"blob store", s.Blob == nil}, {"task events", s.Events == nil},
		{"audit writer (governance)", s.Audit == nil}, {"spend caps (governance)", s.Caps == nil},
		{"run policies (governance)", s.Policies == nil}, {"agent definitions (agents)", s.Agents == nil},
		{"model resolver (models)", s.Resolver == nil}, {"model caller (models)", s.Models == nil},
		{"run definitions (connections, catalog, projects)", s.Definitions == nil},
		{"sandbox runtime (sandbox)", s.Runtime == nil}, {"task workspace (sandbox)", s.Workspace == nil},
		{"skill packages (catalog)", s.Skills == nil}, {"tool callers (connections)", len(s.Tools) == 0},
		{"vendor settlement (connections)", s.Vendor == nil},
		{"executor", m.d.Executor == nil}, {"agent queue", m.d.AgentQueue == ""},
	} {
		if p.nil {
			out = append(out, p.name)
		}
	}
	return append(out, m.d.Scheduling.Missing()...)
}

// Settlement is the worker's cost settlement loop: billing holds captured,
// pending conversions made, vendor costs re-read (cost_settlement.py).
func (m *Module) Settlement() lifecycle.Component {
	return lifecycle.Loop("cost settlement", m.svc.RunSettlement)
}
