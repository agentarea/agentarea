package handlers

import (
	"context"
	"errors"
	"net/http"
	"strconv"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/runs"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/service"
)

// Server implements the runs routes (api/v1/agents_tasks.py, inbox.py,
// tool_call_approvals.py).
type Server struct {
	s     *service.Surface
	audit governanceapi.AuditWriter
	// authority is requires_task_authority.
	authority func(ctx context.Context, taskID string) error
}

var _ gen.StrictServerInterface = (*Server)(nil)

// New builds the server; audit is governance's writer the approval decision records with.
func New(s *service.Surface, audit governanceapi.AuditWriter) *Server {
	return &Server{s: s, audit: audit, authority: s.RequireTaskAuthority}
}

// errUnmounted answers an operation whose route is not mounted in this process.
var errUnmounted = errors.New("route not mounted: its provider is not ported")

// MapError renders the module's errors as Python raises them; the service
// already answers with *httpx.Error, and a refused requires() is 403.
func MapError(err error) (*httpx.Error, bool) {
	if errors.Is(err, authz.ErrDenied) {
		return httpx.HTTPError(http.StatusForbidden, "Permission denied"), true
	}
	return nil, false
}

// response is a JSONResponse body as Starlette writes it.
type response struct {
	status int
	body   any
}

func (x response) visit(w http.ResponseWriter) error {
	raw, err := wirejson.Marshal(x.body, wirejson.Compact)
	if err != nil {
		return err
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Length", strconv.Itoa(len(raw)))
	w.WriteHeader(x.status)
	_, err = w.Write(raw)
	return err
}

func ok(body any, err error) (response, error) {
	if err != nil {
		return response{}, err
	}
	return response{status: http.StatusOK, body: body}, nil
}

func listOf(items []wirejson.Object, err error) (response, error) {
	if err != nil {
		return response{}, err
	}
	out := make([]any, len(items))
	for i, it := range items {
		out[i] = it
	}
	return response{status: http.StatusOK, body: out}, nil
}

func (h *Server) UploadTaskFileV1RunnerTasksTaskIdFilesFilePathPut(context.Context, gen.UploadTaskFileV1RunnerTasksTaskIdFilesFilePathPutRequestObject) (gen.UploadTaskFileV1RunnerTasksTaskIdFilesFilePathPutResponseObject, error) {
	return nil, errUnmounted
}

func (h *Server) RunnerWhoamiV1RunnerWhoamiGet(context.Context, gen.RunnerWhoamiV1RunnerWhoamiGetRequestObject) (gen.RunnerWhoamiV1RunnerWhoamiGetResponseObject, error) {
	return nil, errUnmounted
}

func (h *Server) ListAgentTasksV1AgentsAgentIdTasksGet(ctx context.Context, rq gen.ListAgentTasksV1AgentsAgentIdTasksGetRequestObject) (gen.ListAgentTasksV1AgentsAgentIdTasksGetResponseObject, error) {
	in := inputFrom(ctx)
	return listOf(h.s.ListAgentTasks(ctx, rq.AgentId.String(), in.status, in.limit, in.offset))
}

func (h *Server) CreateTaskForAgentWithStreamV1AgentsAgentIdTasksPost(context.Context, gen.CreateTaskForAgentWithStreamV1AgentsAgentIdTasksPostRequestObject) (gen.CreateTaskForAgentWithStreamV1AgentsAgentIdTasksPostResponseObject, error) {
	return nil, errUnmounted
}

func (h *Server) ScheduleTaskForAgentV1AgentsAgentIdTasksSchedulePost(ctx context.Context, rq gen.ScheduleTaskForAgentV1AgentsAgentIdTasksSchedulePostRequestObject) (gen.ScheduleTaskForAgentV1AgentsAgentIdTasksSchedulePostResponseObject, error) {
	t, err := h.startSync(ctx, inputFrom(ctx).create, rq.AgentId.String())
	if err != nil {
		return nil, err
	}
	body, err := h.s.TaskResponse(ctx, t)
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusCreated, body: body}, nil
}

func (h *Server) CreateTaskForAgentSyncV1AgentsAgentIdTasksSyncPost(ctx context.Context, rq gen.CreateTaskForAgentSyncV1AgentsAgentIdTasksSyncPostRequestObject) (gen.CreateTaskForAgentSyncV1AgentsAgentIdTasksSyncPostResponseObject, error) {
	t, err := h.startSync(ctx, inputFrom(ctx).create, rq.AgentId.String())
	if err != nil {
		return nil, err
	}
	return ok(h.s.TaskResponse(ctx, t))
}

func (h *Server) CancelAgentTaskV1AgentsAgentIdTasksTaskIdDelete(ctx context.Context, rq gen.CancelAgentTaskV1AgentsAgentIdTasksTaskIdDeleteRequestObject) (gen.CancelAgentTaskV1AgentsAgentIdTasksTaskIdDeleteResponseObject, error) {
	return ok(h.s.Cancel(ctx, rq.AgentId.String(), rq.TaskId.String()))
}

func (h *Server) GetAgentTaskV1AgentsAgentIdTasksTaskIdGet(ctx context.Context, rq gen.GetAgentTaskV1AgentsAgentIdTasksTaskIdGetRequestObject) (gen.GetAgentTaskV1AgentsAgentIdTasksTaskIdGetResponseObject, error) {
	return ok(h.s.GetAgentTask(ctx, rq.AgentId.String(), rq.TaskId.String()))
}

func (h *Server) SendA2uiActionV1AgentsAgentIdTasksTaskIdA2uiActionPost(ctx context.Context, rq gen.SendA2uiActionV1AgentsAgentIdTasksTaskIdA2uiActionPostRequestObject) (gen.SendA2uiActionV1AgentsAgentIdTasksTaskIdA2uiActionPostResponseObject, error) {
	return ok(h.s.SendA2UIAction(ctx, rq.AgentId.String(), rq.TaskId.String(), inputFrom(ctx).a2ui))
}

func (h *Server) ListTaskArtifactsV1AgentsAgentIdTasksTaskIdArtifactsGet(ctx context.Context, rq gen.ListTaskArtifactsV1AgentsAgentIdTasksTaskIdArtifactsGetRequestObject) (gen.ListTaskArtifactsV1AgentsAgentIdTasksTaskIdArtifactsGetResponseObject, error) {
	return ok(h.s.Artifacts(ctx, rq.AgentId.String(), rq.TaskId.String()))
}

func (h *Server) DownloadTaskArtifactV1AgentsAgentIdTasksTaskIdArtifactsFilesArtifactPathGet(context.Context, gen.DownloadTaskArtifactV1AgentsAgentIdTasksTaskIdArtifactsFilesArtifactPathGetRequestObject) (gen.DownloadTaskArtifactV1AgentsAgentIdTasksTaskIdArtifactsFilesArtifactPathGetResponseObject, error) {
	return nil, errUnmounted
}

func (h *Server) SendTaskCommandV1AgentsAgentIdTasksTaskIdCommandPost(ctx context.Context, rq gen.SendTaskCommandV1AgentsAgentIdTasksTaskIdCommandPostRequestObject) (gen.SendTaskCommandV1AgentsAgentIdTasksTaskIdCommandPostResponseObject, error) {
	return ok(h.s.SendCommand(ctx, rq.AgentId.String(), rq.TaskId.String(), inputFrom(ctx).command))
}

func (h *Server) ListPendingEscalationsV1AgentsAgentIdTasksTaskIdEscalationsGet(ctx context.Context, rq gen.ListPendingEscalationsV1AgentsAgentIdTasksTaskIdEscalationsGetRequestObject) (gen.ListPendingEscalationsV1AgentsAgentIdTasksTaskIdEscalationsGetResponseObject, error) {
	return ok(h.s.ListEscalations(ctx, rq.AgentId.String(), rq.TaskId.String()))
}

func (h *Server) GetTaskEventsV1AgentsAgentIdTasksTaskIdEventsGet(ctx context.Context, rq gen.GetTaskEventsV1AgentsAgentIdTasksTaskIdEventsGetRequestObject) (gen.GetTaskEventsV1AgentsAgentIdTasksTaskIdEventsGetResponseObject, error) {
	in := inputFrom(ctx)
	return ok(h.s.EventsPage(ctx, rq.AgentId.String(), rq.TaskId.String(), in.page, in.size, in.eventType))
}

// StreamTaskEvents is served by stream, a plain handler: an event stream
// needs the request, which the strict handler does not pass on.
func (h *Server) StreamTaskEventsV1AgentsAgentIdTasksTaskIdEventsStreamGet(context.Context, gen.StreamTaskEventsV1AgentsAgentIdTasksTaskIdEventsStreamGetRequestObject) (gen.StreamTaskEventsV1AgentsAgentIdTasksTaskIdEventsStreamGetResponseObject, error) {
	return nil, errUnmounted
}

func (h *Server) SubmitTaskInputV1AgentsAgentIdTasksTaskIdInputPost(ctx context.Context, rq gen.SubmitTaskInputV1AgentsAgentIdTasksTaskIdInputPostRequestObject) (gen.SubmitTaskInputV1AgentsAgentIdTasksTaskIdInputPostResponseObject, error) {
	return ok(h.s.SubmitInput(ctx, rq.AgentId.String(), rq.TaskId.String(), inputFrom(ctx).submission))
}

func (h *Server) PauseAgentTaskV1AgentsAgentIdTasksTaskIdPausePost(ctx context.Context, rq gen.PauseAgentTaskV1AgentsAgentIdTasksTaskIdPausePostRequestObject) (gen.PauseAgentTaskV1AgentsAgentIdTasksTaskIdPausePostResponseObject, error) {
	return ok(h.s.Pause(ctx, rq.AgentId.String(), rq.TaskId.String()))
}

func (h *Server) ResolveTaskEscalationV1AgentsAgentIdTasksTaskIdResolveEscalationPost(ctx context.Context, rq gen.ResolveTaskEscalationV1AgentsAgentIdTasksTaskIdResolveEscalationPostRequestObject) (gen.ResolveTaskEscalationV1AgentsAgentIdTasksTaskIdResolveEscalationPostResponseObject, error) {
	return ok(h.s.ResolveEscalation(ctx, rq.AgentId.String(), rq.TaskId.String(), inputFrom(ctx).resolution))
}

func (h *Server) ResumeAgentTaskV1AgentsAgentIdTasksTaskIdResumePost(ctx context.Context, rq gen.ResumeAgentTaskV1AgentsAgentIdTasksTaskIdResumePostRequestObject) (gen.ResumeAgentTaskV1AgentsAgentIdTasksTaskIdResumePostResponseObject, error) {
	return ok(h.s.Resume(ctx, rq.AgentId.String(), rq.TaskId.String()))
}

func (h *Server) RetryAgentTaskV1AgentsAgentIdTasksTaskIdRetryPost(ctx context.Context, rq gen.RetryAgentTaskV1AgentsAgentIdTasksTaskIdRetryPostRequestObject) (gen.RetryAgentTaskV1AgentsAgentIdTasksTaskIdRetryPostResponseObject, error) {
	return ok(h.s.Retry(ctx, rq.AgentId.String(), rq.TaskId.String()))
}

func (h *Server) ListTaskSandboxFilesV1AgentsAgentIdTasksTaskIdSandboxFilesGet(ctx context.Context, rq gen.ListTaskSandboxFilesV1AgentsAgentIdTasksTaskIdSandboxFilesGetRequestObject) (gen.ListTaskSandboxFilesV1AgentsAgentIdTasksTaskIdSandboxFilesGetResponseObject, error) {
	return ok(h.s.SandboxFiles(ctx, rq.AgentId.String(), rq.TaskId.String(), inputFrom(ctx).prefix))
}

func (h *Server) ReadTaskSandboxFileV1AgentsAgentIdTasksTaskIdSandboxFilesFilePathGet(context.Context, gen.ReadTaskSandboxFileV1AgentsAgentIdTasksTaskIdSandboxFilesFilePathGetRequestObject) (gen.ReadTaskSandboxFileV1AgentsAgentIdTasksTaskIdSandboxFilesFilePathGetResponseObject, error) {
	return nil, errUnmounted
}

func (h *Server) GetAgentTaskStatusV1AgentsAgentIdTasksTaskIdStatusGet(ctx context.Context, rq gen.GetAgentTaskStatusV1AgentsAgentIdTasksTaskIdStatusGetRequestObject) (gen.GetAgentTaskStatusV1AgentsAgentIdTasksTaskIdStatusGetResponseObject, error) {
	return ok(h.s.TaskStatus(ctx, rq.AgentId.String(), rq.TaskId.String()))
}

func (h *Server) GetTaskSummaryV1AgentsAgentIdTasksTaskIdSummaryGet(ctx context.Context, rq gen.GetTaskSummaryV1AgentsAgentIdTasksTaskIdSummaryGetRequestObject) (gen.GetTaskSummaryV1AgentsAgentIdTasksTaskIdSummaryGetResponseObject, error) {
	return ok(h.s.Summary(ctx, rq.AgentId.String(), rq.TaskId.String()))
}

func (h *Server) GetInboxItemsV1InboxGet(ctx context.Context, _ gen.GetInboxItemsV1InboxGetRequestObject) (gen.GetInboxItemsV1InboxGetResponseObject, error) {
	in := inputFrom(ctx)
	return ok(h.s.Inbox(ctx, in.status, in.agentID, in.page, in.size))
}

func (h *Server) ListApprovalDecisionsV1InboxDecisionsGet(ctx context.Context, _ gen.ListApprovalDecisionsV1InboxDecisionsGetRequestObject) (gen.ListApprovalDecisionsV1InboxDecisionsGetResponseObject, error) {
	in := inputFrom(ctx)
	return ok(h.s.Decisions(ctx, in.page, in.size))
}

func (h *Server) GetAllTasksV1TasksGet(ctx context.Context, _ gen.GetAllTasksV1TasksGetRequestObject) (gen.GetAllTasksV1TasksGetResponseObject, error) {
	in := inputFrom(ctx)
	return listOf(h.s.ListTasks(ctx, service.TaskQuery{
		Statuses: in.statuses, CreatedBy: in.createdBy, Search: in.search, Limit: in.limit, Offset: in.offset,
	}))
}

func (h *Server) GetTaskByIdV1TasksTaskIdGet(ctx context.Context, rq gen.GetTaskByIdV1TasksTaskIdGetRequestObject) (gen.GetTaskByIdV1TasksTaskIdGetResponseObject, error) {
	return ok(h.s.GetTask(ctx, rq.TaskId.String()))
}

func (h *Server) ContinueTaskExecutionV1TasksTaskIdContinuePost(ctx context.Context, rq gen.ContinueTaskExecutionV1TasksTaskIdContinuePostRequestObject) (gen.ContinueTaskExecutionV1TasksTaskIdContinuePostResponseObject, error) {
	return ok(h.s.ContinueExecution(ctx, rq.TaskId.String(), inputFrom(ctx).continuation))
}

func (h *Server) ListToolCallApprovalsV1ToolCallApprovalsGet(ctx context.Context, _ gen.ListToolCallApprovalsV1ToolCallApprovalsGetRequestObject) (gen.ListToolCallApprovalsV1ToolCallApprovalsGetResponseObject, error) {
	in := inputFrom(ctx)
	return ok(h.s.ListApprovals(ctx, in.status, in.page, in.size))
}

func (h *Server) GetToolCallApprovalV1ToolCallApprovalsApprovalIdGet(ctx context.Context, rq gen.GetToolCallApprovalV1ToolCallApprovalsApprovalIdGetRequestObject) (gen.GetToolCallApprovalV1ToolCallApprovalsApprovalIdGetResponseObject, error) {
	return ok(h.s.GetApproval(ctx, rq.ApprovalId))
}

func (h *Server) DecideToolCallApprovalV1ToolCallApprovalsApprovalIdDecidePost(ctx context.Context, rq gen.DecideToolCallApprovalV1ToolCallApprovalsApprovalIdDecidePostRequestObject) (gen.DecideToolCallApprovalV1ToolCallApprovalsApprovalIdDecidePostResponseObject, error) {
	in := inputFrom(ctx)
	return ok(h.s.DecideApproval(ctx, h.audit, rq.ApprovalId, in.approved, in.comment))
}

// stream is stream_task_events: the task is checked before the response
// starts, then the feed runs with a ping after each silent interval.
func (h *Server) stream(errs *httpx.Errors) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		ctx := r.Context()
		in := inputFrom(ctx)
		st, err := h.s.OpenStream(ctx, service.StreamRequest{
			AgentID: chiParam(r, "agent_id"), TaskID: chiParam(r, "task_id"),
			IncludeChunks: in.includeChunks, LastEventID: httpx.LastEventID(r), Follow: true,
		})
		if err != nil {
			errs.Write(w, r, err)
			return
		}
		sse, err := httpx.StartSSE(w, r)
		if err != nil {
			h.s.Log().ErrorContext(ctx, "Failed to start the task event stream", "error", err.Error())
			return
		}
		frames := make(chan []byte)
		runCtx, cancel := context.WithCancel(ctx)
		defer cancel()
		go func() {
			defer close(frames)
			emit := func(eventType string, data wirejson.Object, id string) error {
				frame, err := httpx.FormatSSE(eventType, data, id)
				if err != nil {
					return err
				}
				select {
				case frames <- frame:
					return nil
				case <-runCtx.Done():
					return runCtx.Err()
				}
			}
			if err := st.Run(runCtx, emit); err != nil && runCtx.Err() == nil {
				h.s.Log().ErrorContext(ctx, "Error in task event stream", "task_id", st.TaskID, "error", err.Error())
				frame, ferr := httpx.FormatSSE("error", st.ErrorFrame(h.s.Now()), "")
				if ferr != nil {
					h.s.Log().ErrorContext(ctx, "Failed to format the stream's error frame", "error", ferr.Error())
					return
				}
				select {
				case frames <- frame:
				case <-runCtx.Done():
				}
			}
		}()
		if err := sse.Pump(runCtx, frames, httpx.SSEHeartbeat); err != nil && ctx.Err() == nil {
			h.s.Log().InfoContext(ctx, "Task event stream ended", "task_id", st.TaskID, "reason", err.Error())
		}
	}
}
