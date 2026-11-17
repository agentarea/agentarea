package runs

import (
	"context"
	"errors"
	"net/http"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"

	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/handlers"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/store"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/workflows"
	"github.com/agentarea/agentarea/agentarea-go/internal/serve"
)

// SurfaceDeps are what the runs HTTP surface needs; app passes them in.
type SurfaceDeps struct {
	// Service's Executor is left nil: Durable supplies it when a route first needs it.
	Service service.SurfaceDeps
	Durable ExecutorSource
	// Audit is governance's writer; nil leaves the approval decision unmounted.
	Audit governanceapi.AuditWriter
	// Workspace admits the caller into /v1/workspaces/{workspace}.
	Workspace func(http.Handler) http.Handler
	// AgentQueue is AGENTAREA_TEMPORAL_QUEUE, read when a run starts.
	AgentQueue func() string
}

// Surface is the runs module's HTTP surface, built once per serve process.
type Surface struct {
	d SurfaceDeps
	s *service.Surface
}

// NewSurface constructs the surface.
func NewSurface(d SurfaceDeps) *Surface {
	if d.Service.Executor == nil && d.Durable != nil {
		d.Service.Executor = lazyExecutor{d.Durable}
	}
	if d.Service.Executor != nil && d.AgentQueue != nil {
		l := runStarter{exec: d.Service.Executor, queue: d.AgentQueue, now: d.Service.Now}
		if d.Service.Launcher == nil {
			d.Service.Launcher = l
		}
		if d.Service.Resumer == nil {
			d.Service.Resumer = l
		}
	}
	return &Surface{d: d, s: service.NewSurface(d.Service)}
}

// Tasks starts runs for other modules (route_or_submit_task).
func (m *Surface) Tasks() api.Tasks { return m.s }

// Serve is the module's HTTP surface.
func (m *Surface) Serve() serve.Module {
	return serve.Module{
		Name:   "runs",
		Errors: handlers.MapError,
		Mount: func(rt serve.Routes) error {
			handlers.Mount(rt.Mux.Chi(), rt.Errors, m.d.Workspace, handlers.New(m.s, m.d.Audit))
			return nil
		},
	}
}

// runStarter starts a task's workflow on the agent queue named when it starts.
type runStarter struct {
	exec  durable.Executor
	queue func() string
	now   func() time.Time
}

func (r runStarter) launcher() workflows.Launcher {
	return workflows.Launcher{Exec: r.exec, Queue: r.queue(), Now: r.now}
}

func (r runStarter) Launch(ctx context.Context, workspaceID string, t store.StoredTask) (service.Launched, error) {
	return r.launcher().Launch(ctx, workspaceID, t)
}

// Resume is TemporalTaskManager.resume_task: a new run of the task's
// workflow picking the conversation up where the log ends.
func (r runStarter) Resume(ctx context.Context, workspaceID string, t store.StoredTask, sp service.ResumeSpec) error {
	queue := r.queue()
	if queue == "" {
		return errors.New("resuming a run needs the agent queue")
	}
	meta := map[string]any{}
	for k, v := range t.Metadata {
		if k != "conversation_resume" {
			meta[k] = v
		}
	}
	t.Metadata = meta
	req, err := workflows.RunRequestFromTask(workspaceID, t)
	if err != nil {
		return err
	}
	req.Resume = &workflows.RunResume{
		Snapshot: workflows.ResumeSnapshot{
			NextSeq: sp.NextSeq, CurrentIteration: sp.CurrentIteration, ToolCallsUsed: sp.ToolCallsUsed,
			TokensUsed: sp.TokensUsed, LastPromptTokens: sp.LastPromptTokens,
		},
		TotalCost: sp.TotalCost, OwnCost: sp.OwnCost, LLMCost: sp.LLMCost,
		SystemPromptMissing: sp.SystemPromptMissing, Retry: sp.Retry,
	}
	opts := durable.StartOptions{TaskQueue: queue, RetryAttempts: 1}
	if sp.Message != nil {
		opts.StartSignal = api.SignalWorkflowCommand
		opts.StartSignalArgs = []any{api.WorkflowCommandSignal{Command: api.CommandQueueMessage, Payload: map[string]any{"message": *sp.Message, "sender": sp.Sender}}}
	}
	_, err = r.exec.Start(ctx, api.WorkflowAgentExecution, workflows.TaskWorkflowID(t.ID), []any{req}, opts)
	return err
}

// ExecutorSource is the process's Temporal client, opened before routes are served.
type ExecutorSource interface {
	Executor() durable.Executor
}

// lazyExecutor asks the source for its executor on each call, so the
// surface can be built before the client is opened.
type lazyExecutor struct{ src ExecutorSource }

func (l lazyExecutor) Start(ctx context.Context, workflow, workflowID string, args []any, opts durable.StartOptions) (string, error) {
	return l.src.Executor().Start(ctx, workflow, workflowID, args, opts)
}
func (l lazyExecutor) Status(ctx context.Context, workflowID string) (durable.Result, error) {
	return l.src.Executor().Status(ctx, workflowID)
}
func (l lazyExecutor) Cancel(ctx context.Context, workflowID string) error {
	return l.src.Executor().Cancel(ctx, workflowID)
}
func (l lazyExecutor) Wait(ctx context.Context, workflowID string, timeout time.Duration) (durable.Result, error) {
	return l.src.Executor().Wait(ctx, workflowID, timeout)
}
func (l lazyExecutor) Signal(ctx context.Context, workflowID, signal string, args ...any) error {
	return l.src.Executor().Signal(ctx, workflowID, signal, args...)
}
func (l lazyExecutor) Query(ctx context.Context, workflowID, query string, out any, args ...any) error {
	return l.src.Executor().Query(ctx, workflowID, query, out, args...)
}
func (l lazyExecutor) Update(ctx context.Context, workflowID, update string, out any, args ...any) error {
	return l.src.Executor().Update(ctx, workflowID, update, out, args...)
}

// HeldCalls passes calls outside a run that the policy holds through their approval.
func (m *Surface) HeldCalls() api.HeldCalls { return m.s }
