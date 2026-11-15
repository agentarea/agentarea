package handlers

import (
	"context"
	"net/http"

	"github.com/go-chi/chi/v5"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/runs"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	sandboxapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
)

func chiParam(r *http.Request, name string) string { return chi.URLParam(r, name) }

// Mount registers the runs routes on r behind workspace, the edge's
// middleware that admits the caller into /v1/workspaces/{workspace}.
// decide is mounted only with governance's audit writer, decisions only
// with its audit reader.
func Mount(r chi.Router, errs *httpx.Errors, workspace func(http.Handler) http.Handler, h *Server) {
	w := &gen.ServerInterfaceWrapper{
		Handler: gen.NewStrictHandlerWithOptions(h, nil, gen.StrictHTTPServerOptions{
			RequestErrorHandlerFunc: errs.Write, ResponseErrorHandlerFunc: errs.Write,
		}),
		ErrorHandlerFunc: errs.Write,
	}
	base := r.With(workspace)
	on := func(rq request) chi.Router { return base.With(rq.middleware(errs)) }
	authority := func(ctx context.Context, taskID string) error { return h.authority(ctx, taskID) }
	p := httpx.WorkspacePrefix
	at := p + "/agents/{agent_id}/tasks"
	agent := []string{"agent_id"}
	task := []string{"agent_id", "task_id"}

	on(request{pathUUIDs: agent, query: agentTasksQuery}).Get(at+"/", w.ListAgentTasksV1AgentsAgentIdTasksGet)
	if h.s.CreateMounted() {
		execute := h.s.RequireExecute
		on(request{pathUUIDs: agent, execute: execute, query: followQuery, body: createBody}).Post(at+"/", h.create(errs))
		on(request{pathUUIDs: agent, execute: execute, body: createBody}).Post(at+"/sync", w.CreateTaskForAgentSyncV1AgentsAgentIdTasksSyncPost)
		on(request{pathUUIDs: agent, execute: execute, body: scheduleBody}).Post(at+"/schedule", w.ScheduleTaskForAgentV1AgentsAgentIdTasksSchedulePost)
	}
	if h.s.ResumeMounted() {
		on(request{pathUUIDs: task, authority: authority}).Post(at+"/{task_id}/retry", w.RetryAgentTaskV1AgentsAgentIdTasksTaskIdRetryPost)
	}
	if h.s.CreateMounted() {
		on(request{pathUUIDs: []string{"task_id"}, authority: authority, body: continueBody}).Post(p+"/tasks/{task_id}/continue", w.ContinueTaskExecutionV1TasksTaskIdContinuePost)
	}
	on(request{pathUUIDs: task}).Get(at+"/{task_id}/status", w.GetAgentTaskStatusV1AgentsAgentIdTasksTaskIdStatusGet)
	if h.s.FilesMounted() {
		on(request{pathUUIDs: task, query: artifactsQuery}).Get(at+"/{task_id}/artifacts", w.ListTaskArtifactsV1AgentsAgentIdTasksTaskIdArtifactsGet)
		on(request{pathUUIDs: task}).Get(at+"/{task_id}/artifacts/files/*", h.files(errs, func(ctx context.Context, r *http.Request) (sandboxapi.Download, error) {
			return h.s.Artifact(ctx, chiParam(r, "agent_id"), chiParam(r, "task_id"), chiParam(r, "*"))
		}))
		on(request{pathUUIDs: task, query: sandboxPrefixQuery}).Get(at+"/{task_id}/sandbox/files", w.ListTaskSandboxFilesV1AgentsAgentIdTasksTaskIdSandboxFilesGet)
		on(request{pathUUIDs: task}).Get(at+"/{task_id}/sandbox/files/*", h.files(errs, func(ctx context.Context, r *http.Request) (sandboxapi.Download, error) {
			return h.s.SandboxFile(ctx, chiParam(r, "agent_id"), chiParam(r, "task_id"), chiParam(r, "*"))
		}))
	}
	on(request{pathUUIDs: task, authority: authority}).Delete(at+"/{task_id}", w.CancelAgentTaskV1AgentsAgentIdTasksTaskIdDelete)
	on(request{pathUUIDs: task}).Get(at+"/{task_id}", w.GetAgentTaskV1AgentsAgentIdTasksTaskIdGet)
	on(request{pathUUIDs: task, body: a2uiBody, authority: authority}).Post(at+"/{task_id}/a2ui/action", w.SendA2uiActionV1AgentsAgentIdTasksTaskIdA2uiActionPost)
	on(request{pathUUIDs: task, body: commandBody, authority: authority}).Post(at+"/{task_id}/command", w.SendTaskCommandV1AgentsAgentIdTasksTaskIdCommandPost)
	on(request{pathUUIDs: task}).Get(at+"/{task_id}/escalations", w.ListPendingEscalationsV1AgentsAgentIdTasksTaskIdEscalationsGet)
	on(request{pathUUIDs: task, query: eventsQuery}).Get(at+"/{task_id}/events", w.GetTaskEventsV1AgentsAgentIdTasksTaskIdEventsGet)
	on(request{pathUUIDs: task, query: streamQuery}).Get(at+"/{task_id}/events/stream", h.stream(errs))
	on(request{pathUUIDs: task, body: inputBody, authority: authority}).Post(at+"/{task_id}/input", w.SubmitTaskInputV1AgentsAgentIdTasksTaskIdInputPost)
	on(request{pathUUIDs: task, authority: authority}).Post(at+"/{task_id}/pause", w.PauseAgentTaskV1AgentsAgentIdTasksTaskIdPausePost)
	on(request{pathUUIDs: task, body: resolutionBody}).Post(at+"/{task_id}/resolve-escalation", w.ResolveTaskEscalationV1AgentsAgentIdTasksTaskIdResolveEscalationPost)
	on(request{pathUUIDs: task, authority: authority}).Post(at+"/{task_id}/resume", w.ResumeAgentTaskV1AgentsAgentIdTasksTaskIdResumePost)
	on(request{pathUUIDs: task}).Get(at+"/{task_id}/summary", w.GetTaskSummaryV1AgentsAgentIdTasksTaskIdSummaryGet)

	on(request{query: inboxQuery}).Get(p+"/inbox/", w.GetInboxItemsV1InboxGet)
	if h.s.DecisionsMounted() {
		on(request{query: decisionsQuery}).Get(p+"/inbox/decisions", w.ListApprovalDecisionsV1InboxDecisionsGet)
	}
	on(request{query: allTasksQuery}).Get(p+"/tasks/", w.GetAllTasksV1TasksGet)
	on(request{pathUUIDs: []string{"task_id"}}).Get(p+"/tasks/{task_id}", w.GetTaskByIdV1TasksTaskIdGet)

	on(request{query: approvalsQuery}).Get(p+"/tool-call-approvals", w.ListToolCallApprovalsV1ToolCallApprovalsGet)
	on(request{}).Get(p+"/tool-call-approvals/{approval_id}", w.GetToolCallApprovalV1ToolCallApprovalsApprovalIdGet)
	if h.audit != nil {
		on(request{body: decisionBody}).Post(p+"/tool-call-approvals/{approval_id}/decide", w.DecideToolCallApprovalV1ToolCallApprovalsApprovalIdDecidePost)
	}
}
