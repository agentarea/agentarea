package service

import (
	"context"
	"errors"
	"net/http"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
)

// TaskQuery is GET /tasks/'s filters.
type TaskQuery struct {
	Statuses  []string
	CreatedBy *string
	Search    *string
	Limit     int
	Offset    int
}

func (s *Surface) names(ctx context.Context, ws scope.Workspace, ids []string) (map[string]string, error) {
	if len(ids) == 0 {
		return map[string]string{}, nil
	}
	return s.d.Agents.AgentNames(ctx, ws, ids)
}

func nameOf(names map[string]string, id string) any {
	if n, ok := names[id]; ok {
		return n
	}
	return nil
}

// ListTasks is get_all_tasks: one page of the workspace's tasks, newest first.
func (s *Surface) ListTasks(ctx context.Context, q TaskQuery) ([]wirejson.Object, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	sess, release, err := s.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return nil, s.internal(ctx, "Failed to get all tasks", err)
	}
	defer release()
	queries := store.New(sess.Q())
	agentIDs, err := queries.SurfaceTaskAgentIDs(ctx, c.Workspace.ID())
	if err != nil {
		return nil, s.internal(ctx, "Failed to get all tasks", err)
	}
	ids := make([]string, len(agentIDs))
	for i, id := range agentIDs {
		ids[i] = id.String()
	}
	names, err := s.names(ctx, c.Workspace, ids)
	if err != nil {
		return nil, s.internal(ctx, "Failed to get all tasks", err)
	}
	searchAgents := []uuid.UUID{}
	if q.Search != nil && *q.Search != "" {
		needle := strings.ToLower(*q.Search)
		for _, id := range agentIDs {
			if n, ok := names[id.String()]; ok && strings.Contains(strings.ToLower(n), needle) {
				searchAgents = append(searchAgents, id)
			}
		}
	}
	statuses := q.Statuses
	if statuses == nil {
		statuses = []string{}
	}
	search := store.Text(nil)
	if q.Search != nil && *q.Search != "" {
		escaped := likeEscape(*q.Search)
		search = store.Text(&escaped)
	}
	rows, err := queries.SurfaceTaskPage(ctx, store.SurfaceTaskPageParams{
		WorkspaceID: c.Workspace.ID(), Statuses: statuses, CreatedBy: store.Text(q.CreatedBy),
		Search: search, SearchAgentIds: searchAgents, Skip: int32(q.Offset), MaxRows: int32(q.Limit),
	})
	if err != nil {
		return nil, s.internal(ctx, "Failed to get all tasks", err)
	}
	out := make([]wirejson.Object, 0, len(rows))
	for _, r := range rows {
		t, err := taskOf(store.SurfaceTaskRow(r))
		if err != nil {
			return nil, s.internal(ctx, "Failed to get all tasks", err)
		}
		out = append(out, TaskWithAgentJSON(t, c, nameOf(names, t.AgentID), nil, nil))
	}
	return out, nil
}

// likeEscape escapes LIKE's wildcards with '/', as icontains(autoescape=True) does.
func likeEscape(s string) string {
	r := strings.NewReplacer("/", "//", "%", "/%", "_", "/_")
	return r.Replace(s)
}

// GetTask is get_task_by_id.
func (s *Surface) GetTask(ctx context.Context, taskID string) (wirejson.Object, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	t, ok, err := s.loadTask(ctx, c.Workspace, taskID)
	if err != nil {
		return nil, s.internal(ctx, "Failed to get task", err)
	}
	if !ok {
		return nil, notFound("Task not found")
	}
	names, err := s.names(ctx, c.Workspace, []string{t.AgentID})
	if err != nil {
		return nil, s.internal(ctx, "Failed to get task", err)
	}
	return TaskWithAgentJSON(t, c, nameOf(names, t.AgentID), nil, nil), nil
}

// ListAgentTasks is list_agent_tasks.
func (s *Surface) ListAgentTasks(ctx context.Context, agentID string, status *string, limit, offset int) ([]wirejson.Object, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.requireAgent(ctx, c.Workspace, agentID); err != nil {
		return nil, err
	}
	st := store.Text(nil)
	if status != nil && *status != "" {
		lower := strings.ToLower(*status)
		st = store.Text(&lower)
	}
	id, _ := parseID(agentID)
	sess, release, err := s.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return nil, s.internal(ctx, "Failed to get tasks for agent", err)
	}
	defer release()
	rows, err := store.New(sess.Q()).SurfaceAgentTasks(ctx, store.SurfaceAgentTasksParams{
		WorkspaceID: c.Workspace.ID(), AgentID: id, Status: st, Skip: int32(offset), MaxRows: int32(limit),
	})
	if err != nil {
		return nil, s.internal(ctx, "Failed to get tasks for agent", err)
	}
	out := make([]wirejson.Object, 0, len(rows))
	for _, r := range rows {
		t, err := taskOf(store.SurfaceTaskRow(r))
		if err != nil {
			return nil, s.internal(ctx, "Failed to get tasks for agent", err)
		}
		out = append(out, TaskResponseJSON(t, c))
	}
	return out, nil
}

// closedExecutionStatuses is _CLOSED_EXECUTION_STATUSES.
func closedExecutionStatuses(s string) bool {
	switch s {
	case "completed", "failed", "cancelled", "canceled":
		return true
	}
	return false
}

// enrich is _enrich_task_with_workflow_status: a closed run's business
// outcome replaces a status the run did not store as ended, in memory only.
func (s *Surface) enrich(ctx context.Context, t Task) Task {
	if t.ExecutionID == nil || *t.ExecutionID == "" {
		return t
	}
	ws := s.workflowStatus(ctx, *t.ExecutionID)
	exec := ws.ExecutionStatus
	if exec == "" {
		exec = ws.Status
	}
	if !closedExecutionStatuses(exec) || endedStatuses(t.Status) {
		return t
	}
	var resultStatus string
	if ws.Result != nil {
		v, _ := ws.Result.Get("status")
		resultStatus, _ = v.(string)
	}
	outcome := resultStatus
	if outcome == "" {
		outcome = ws.Status
	}
	if outcome == "canceled" {
		outcome = "cancelled"
	}
	if outcome == "completed" && resultStatus != "completed" && ws.Success != true {
		return t
	}
	switch outcome {
	case "completed", "failed", "cancelled", "blocked", "waiting_for_input", "waiting_for_approval", "waiting_for_continuation":
	default:
		return t
	}
	t.Status = outcome
	if ws.Result != nil {
		merged := append(wirejson.Object{}, ws.Result...)
		if stored, ok := t.Result.(wirejson.Object); ok {
			for _, k := range []string{"total_cost", "own_cost", "tokens_used"} {
				if v, ok := stored.Get(k); ok {
					merged.Set(k, v)
				}
			}
		}
		t.Result = merged
	}
	if ws.Error != "" {
		e := ws.Error
		t.Error = &e
	}
	return t
}

// GetAgentTask is get_agent_task.
func (s *Surface) GetAgentTask(ctx context.Context, agentID, taskID string) (wirejson.Object, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	t, ok, err := s.loadTask(ctx, c.Workspace, taskID)
	if err != nil {
		return nil, httpx.HTTPError(http.StatusInternalServerError, "Internal server error").Wrap(err)
	}
	if !ok || t.AgentID != agentID {
		return nil, notFound("Task not found")
	}
	return TaskResponseJSON(s.enrich(ctx, t), c), nil
}

// Summary is get_task_summary.
func (s *Surface) Summary(ctx context.Context, agentID, taskID string) (wirejson.Object, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	t, ok, err := s.loadTask(ctx, c.Workspace, taskID)
	if err != nil {
		return nil, err
	}
	if !ok || t.AgentID != agentID {
		return nil, notFound("Task not found")
	}
	currency := s.d.Currency()
	sess, release, err := s.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return nil, err
	}
	defer release()
	total, err := store.Runs{}.SumSpendSince(ctx, sess, time.Unix(0, 0).UTC(), currency, store.SpendScope{TaskID: t.ID})
	if err != nil {
		return nil, err
	}
	cost, err := money.Parse(total)
	if err != nil {
		return nil, err
	}
	costFloat, _ := asFloat(cost.String())
	var ended *time.Time
	if endedStatuses(t.Status) {
		ended = t.CompletedAt
	}
	var duration any
	if ended != nil && t.StartedAt != nil {
		duration = wirejson.Float(float64(ended.Sub(*t.StartedAt).Microseconds()) / 1000)
	}
	var final any
	if v, ok := getObj(t.Result, "response"); ok {
		if str, isStr := v.(string); isStr {
			final = str
		}
	}
	return wirejson.Object{
		{Key: "task_id", Value: t.ID},
		{Key: "agent_id", Value: t.AgentID},
		{Key: "workspace_id", Value: c.Workspace.ID()},
		{Key: "status", Value: t.Status},
		{Key: "started_at", Value: isoOrNil(t.StartedAt)},
		{Key: "ended_at", Value: isoOrNil(ended)},
		{Key: "duration_ms", Value: duration},
		{Key: "cost", Value: costFloat},
		{Key: "currency", Value: currency},
		{Key: "final_response", Value: final},
		{Key: "last_error", Value: strOrNil(t.Error)},
	}, nil
}

// InboxStatuses is INBOX_STATUSES in order.
func InboxStatuses() []string {
	return []string{"waiting_for_approval", "waiting_for_input", "completed", "failed"}
}

const escalationQueryConcurrency = 8

// Inbox is get_inbox_items.
func (s *Surface) Inbox(ctx context.Context, status *string, agentID *string, page, pageSize int) (wirejson.Object, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	statuses := InboxStatuses()
	if status != nil {
		statuses = []string{*status}
	}
	var agent uuid.NullUUID
	if agentID != nil {
		id, _ := parseID(*agentID)
		agent = uuid.NullUUID{UUID: id, Valid: true}
	}
	sess, release, err := s.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return nil, s.internal(ctx, "Failed to get inbox items", err)
	}
	defer release()
	q := store.New(sess.Q())
	rows, err := q.SurfaceInboxPage(ctx, store.SurfaceInboxPageParams{
		WorkspaceID: c.Workspace.ID(), Statuses: statuses, AgentID: agent,
		Skip: int32((page - 1) * pageSize), MaxRows: int32(pageSize),
	})
	if err != nil {
		return nil, s.internal(ctx, "Failed to get inbox items", err)
	}
	total, err := q.SurfaceInboxCount(ctx, store.SurfaceInboxCountParams{WorkspaceID: c.Workspace.ID(), Statuses: statuses, AgentID: agent})
	if err != nil {
		return nil, s.internal(ctx, "Failed to get inbox items", err)
	}
	tasks := make([]Task, len(rows))
	ids := []string{}
	seen := map[string]bool{}
	for i, r := range rows {
		if tasks[i], err = taskOf(store.SurfaceTaskRow(r)); err != nil {
			return nil, s.internal(ctx, "Failed to get inbox items", err)
		}
		if !seen[tasks[i].AgentID] {
			seen[tasks[i].AgentID] = true
			ids = append(ids, tasks[i].AgentID)
		}
	}
	names, err := s.names(ctx, c.Workspace, ids)
	if err != nil {
		return nil, s.internal(ctx, "Failed to get inbox items", err)
	}
	escalations := s.openEscalations(ctx, tasks)
	items := make([]any, len(tasks))
	for i, t := range tasks {
		var escID, escTool any
		if e, ok := escalations[t.ID]; ok {
			escID, escTool = e.EscalationID, e.ToolName
		}
		var cost any
		if v, ok := getObj(t.Result, "total_cost"); ok && v != nil {
			if f, ok := asFloat(v); ok {
				cost = f
			}
		}
		items[i] = inboxItem(t, nameOf(names, t.AgentID), cost, escID, escTool)
	}
	return wirejson.Object{
		{Key: "items", Value: items}, {Key: "total", Value: total},
		{Key: "page", Value: page}, {Key: "page_size", Value: pageSize},
	}, nil
}

// inboxItem is the TaskWithAgent the inbox builds: no error, caller fields or creator.
func inboxItem(t Task, agentName, cost, escID, escTool any) wirejson.Object {
	return wirejson.Object{
		{Key: "id", Value: t.ID},
		{Key: "agent_id", Value: t.AgentID},
		{Key: "agent_name", Value: agentName},
		{Key: "description", Value: t.Description},
		{Key: "parameters", Value: t.Parameters},
		{Key: "status", Value: t.Status},
		{Key: "result", Value: t.Result},
		{Key: "error", Value: nil},
		{Key: "failure_reason", Value: nil},
		{Key: "created_at", Value: PyISO(t.CreatedAt, true)},
		{Key: "execution_id", Value: strOrNil(t.ExecutionID)},
		{Key: "total_cost", Value: cost},
		{Key: "total_tokens", Value: nil},
		{Key: "end_user_id", Value: nil},
		{Key: "metadata", Value: nil},
		{Key: "scheduled_at", Value: nil},
		{Key: "escalation_id", Value: escID},
		{Key: "escalation_tool_name", Value: escTool},
		{Key: "created_by", Value: nil},
		{Key: "provenance", Value: provenanceJSON(t.Provenance)},
	}
}

// openEscalations is _latest_open_escalation for each task waiting for
// approval, eight at a time; a failure leaves the task without one.
func (s *Surface) openEscalations(ctx context.Context, tasks []Task) map[string]api.PendingEscalationView {
	out := map[string]api.PendingEscalationView{}
	var mu sync.Mutex
	var wg sync.WaitGroup
	slots := make(chan struct{}, escalationQueryConcurrency)
	for _, t := range tasks {
		if t.Status != "waiting_for_approval" {
			continue
		}
		wg.Add(1)
		go func(id string) {
			defer wg.Done()
			slots <- struct{}{}
			pending, err := s.pendingEscalations(ctx, "task-"+id)
			<-slots
			switch {
			case errors.Is(err, errWorkflowNotFound):
				s.d.Log.WarnContext(ctx, "Task waits for approval but has no workflow", "task_id", id)
				return
			case err != nil:
				s.d.Log.ErrorContext(ctx, "Failed to read pending escalations of task", "task_id", id, "error", err.Error())
				return
			case len(pending) == 0:
				return
			}
			mu.Lock()
			out[id] = pending[len(pending)-1]
			mu.Unlock()
		}(t.ID)
	}
	wg.Wait()
	return out
}

func uncancellable(s string) bool {
	switch s {
	case "failed", "blocked", "cancelled":
		return true
	}
	return false
}

// Cancel is cancel_agent_task.
func (s *Surface) Cancel(ctx context.Context, agentID, taskID string) (wirejson.Object, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.requireAgent(ctx, c.Workspace, agentID); err != nil {
		return nil, err
	}
	t, err := s.taskOfAgent(ctx, c.Workspace, agentID, taskID)
	if err != nil {
		return nil, err
	}
	if uncancellable(t.Status) {
		return nil, httpx.HTTPError(http.StatusConflict, "Task already ended: "+t.Status)
	}
	execID := t.executionID()
	var ok bool
	if t.Status == "scheduled" {
		ok, err = s.cancelScheduled(ctx, c.Workspace, t)
		if err != nil {
			return nil, s.internal(ctx, "Failed to cancel task", err)
		}
	} else if err := s.d.Executor.Cancel(ctx, execID); err != nil {
		s.d.Log.ErrorContext(ctx, "Failed to cancel workflow", "workflow_id", execID, "error", err.Error())
	} else {
		ok = true
	}
	if !ok {
		return nil, notFound("Task not found or already completed")
	}
	return wirejson.Object{{Key: "status", Value: "cancelled"}, {Key: "task_id", Value: t.ID}, {Key: "execution_id", Value: execID}}, nil
}

// cancelScheduled is TemporalTaskManager.cancel_task: the delayed workflow
// task-<id> is cancelled and the task stored cancelled.
func (s *Surface) cancelScheduled(ctx context.Context, ws scope.Workspace, t Task) (bool, error) {
	if err := s.d.Executor.Cancel(ctx, "task-"+t.ID); err != nil {
		s.d.Log.ErrorContext(ctx, "Error cancelling task", "task_id", t.ID, "error", err.Error())
		return false, nil
	}
	id, _ := parseID(t.ID)
	now := store.Timestamp(s.d.Now())
	err := s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		_, err := store.New(sess.Q()).SurfaceCancelScheduled(ctx, store.SurfaceCancelScheduledParams{Now: now, ID: id, WorkspaceID: ws.ID()})
		return err
	})
	return err == nil, err
}

// pauseResume is the shared head of pause_agent_task and resume_agent_task.
func (s *Surface) runningTask(ctx context.Context, agentID, taskID, verb string) (authn.Caller, Task, string, error) {
	c, err := caller(ctx)
	if err != nil {
		return c, Task{}, "", err
	}
	if err := s.requireAgent(ctx, c.Workspace, agentID); err != nil {
		return c, Task{}, "", err
	}
	t, err := s.taskOfAgent(ctx, c.Workspace, agentID, taskID)
	if err != nil {
		return c, Task{}, "", err
	}
	execID := t.executionID()
	st := s.workflowStatus(ctx, execID)
	if st.Status == "unknown" {
		return c, t, "", notFound("Task not found")
	}
	current := strings.ToLower(st.Status)
	if finishedWorkflowStates(current) {
		return c, t, "", httpx.HTTPError(http.StatusBadRequest, "Cannot "+verb+" task in '"+current+"' state")
	}
	return c, t, execID, nil
}

// Pause is pause_agent_task.
func (s *Surface) Pause(ctx context.Context, agentID, taskID string) (wirejson.Object, error) {
	_, t, execID, err := s.runningTask(ctx, agentID, taskID, "pause")
	if err != nil {
		return nil, err
	}
	if live := s.liveState(ctx, execID); live != nil && truthyGo(live["paused"]) {
		return nil, httpx.HTTPError(http.StatusBadRequest, "Task is already paused")
	}
	if !s.signal(ctx, execID, api.SignalPause, api.PauseSignal{Reason: "User requested pause"}) {
		return nil, httpx.HTTPError(http.StatusInternalServerError, "Failed to pause task")
	}
	return wirejson.Object{
		{Key: "status", Value: "paused"}, {Key: "task_id", Value: t.ID},
		{Key: "execution_id", Value: execID}, {Key: "message", Value: "Task paused successfully"},
	}, nil
}

// Resume is resume_agent_task.
func (s *Surface) Resume(ctx context.Context, agentID, taskID string) (wirejson.Object, error) {
	_, t, execID, err := s.runningTask(ctx, agentID, taskID, "resume")
	if err != nil {
		return nil, err
	}
	if live := s.liveState(ctx, execID); live != nil && !truthyGo(live["paused"]) && !truthyGo(live["waiting_for_infrastructure"]) {
		return nil, httpx.HTTPError(http.StatusBadRequest, "Task is not paused")
	}
	if !s.signal(ctx, execID, api.SignalResume, api.PauseSignal{Reason: "User requested resume"}) {
		return nil, httpx.HTTPError(http.StatusInternalServerError, "Failed to resume task")
	}
	return wirejson.Object{
		{Key: "status", Value: "running"}, {Key: "task_id", Value: t.ID},
		{Key: "execution_id", Value: execID}, {Key: "message", Value: "Task resumed successfully"},
	}, nil
}

// truthyGo is Python truthiness of a value decoded by encoding/json.
func truthyGo(v any) bool {
	switch v := v.(type) {
	case nil:
		return false
	case bool:
		return v
	case string:
		return v != ""
	case float64:
		return v != 0
	case map[string]any:
		return len(v) > 0
	case []any:
		return len(v) > 0
	}
	return true
}

// A2UIAction is A2UIActionPayload.
type A2UIAction struct {
	Name              string         `json:"name"`
	SurfaceID         string         `json:"surface_id"`
	SourceComponentID string         `json:"source_component_id"`
	Context           map[string]any `json:"context"`
}

// SendA2UIAction is send_a2ui_action.
func (s *Surface) SendA2UIAction(ctx context.Context, agentID, taskID string, a A2UIAction) (wirejson.Object, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := refuseAgentHTTP(c); err != nil {
		return nil, err
	}
	def, err := s.d.Definitions.Definition(ctx, c.Workspace, agentID)
	if errors.Is(err, agentsapi.ErrNotFound) {
		return nil, notFound("Agent not found")
	}
	if err != nil {
		return nil, err
	}
	if !def.A2UIEnabled {
		return nil, httpx.HTTPError(http.StatusBadRequest, "Agent does not have A2UI enabled")
	}
	t, err := s.taskOfAgent(ctx, c.Workspace, agentID, taskID)
	if err != nil {
		return nil, err
	}
	execID := t.executionID()
	st := s.workflowStatus(ctx, execID)
	current := st.ExecutionStatus
	if current == "" {
		current = st.Status
	}
	current = strings.ToLower(current)
	if current == "unknown" {
		return nil, notFound("Task not found")
	}
	if current != "running" {
		return nil, httpx.HTTPError(http.StatusBadRequest, "Cannot send action to task in '"+current+"' state")
	}
	if a.Context == nil {
		a.Context = map[string]any{}
	}
	action := map[string]any{"name": a.Name, "surface_id": a.SurfaceID, "source_component_id": a.SourceComponentID, "context": a.Context}
	if !s.signal(ctx, execID, api.SignalA2UIAction, action) {
		return nil, httpx.HTTPError(http.StatusInternalServerError, "Failed to send action to workflow")
	}
	return wirejson.Object{
		{Key: "status", Value: "accepted"}, {Key: "task_id", Value: t.ID},
		{Key: "action_name", Value: a.Name}, {Key: "message", Value: "Action sent to workflow"},
	}, nil
}

// SecretAnswer is one secret answer: a bare value, or an InputSecretValue.
type SecretAnswer struct {
	Value string
	// Name is InputSecretValue.secret_name; nil when not given or for a bare value.
	Name *string
}

// InputSubmission is TaskInputSubmission.
type InputSubmission struct {
	InputRequestID string
	Answers        wirejson.Object
	Secrets        []SecretField
}

// SecretField is one entry of the submission's secrets, in order.
type SecretField struct {
	Field  string
	Answer SecretAnswer
}

var secretNameSafe = regexp.MustCompile(`[^A-Za-z0-9_.:/-]+`)

// defaultInputSecretName is _default_input_secret_name.
func defaultInputSecretName(taskID, field string) string {
	sanitized := strings.Trim(secretNameSafe.ReplaceAllString(field, "_"), "._:/-")
	if sanitized == "" {
		sanitized = "secret"
	}
	return "task-input/" + taskID + "/" + sanitized
}

// SubmitInput is submit_task_input.
func (s *Surface) SubmitInput(ctx context.Context, agentID, taskID string, in InputSubmission) (wirejson.Object, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := refuseAgentHTTP(c); err != nil {
		return nil, err
	}
	t, err := s.taskOfAgent(ctx, c.Workspace, agentID, taskID)
	if err != nil {
		return nil, err
	}
	if err := s.requireAgent(ctx, c.Workspace, agentID); err != nil {
		return nil, err
	}
	execID := t.executionID()
	st := s.workflowStatus(ctx, execID)
	if st.Status == "unknown" {
		return nil, notFound("Task not found")
	}
	current := strings.ToLower(st.Status)
	if finishedWorkflowStates(current) {
		return nil, httpx.HTTPError(http.StatusBadRequest, "Cannot submit input to task in '"+current+"' state")
	}
	refs := map[string]any{}
	keys := []string{}
	for _, f := range in.Secrets {
		name := defaultInputSecretName(t.ID, f.Field)
		if f.Answer.Name != nil && *f.Answer.Name != "" {
			if secrets.ReservedPrefix(*f.Answer.Name) != "" {
				return nil, httpx.HTTPError(http.StatusUnprocessableEntity, "Secret name '"+*f.Answer.Name+
					"' uses a prefix reserved for secrets the platform manages on behalf of a connection.")
			}
			name = *f.Answer.Name
		}
		err := s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
			return s.d.Secrets(sess, c.UserID).Set(ctx, name, f.Answer.Value)
		})
		if err != nil {
			return nil, s.internal(ctx, "Failed to submit input for task", err)
		}
		if _, dup := refs[f.Field]; !dup {
			keys = append(keys, f.Field)
		}
		refs[f.Field] = map[string]any{"secret_name": name, "secret_ref": "secret:" + name}
	}
	answers := map[string]any{}
	answerKeys := make([]string, 0, len(in.Answers))
	for _, m := range in.Answers {
		answers[m.Key] = plain(m.Value)
		answerKeys = append(answerKeys, m.Key)
	}
	payload := map[string]any{
		"input_request_id": in.InputRequestID, "answers": answers, "secret_refs": refs, "submitted_by": c.UserID,
	}
	if !s.command(ctx, execID, api.CommandSubmitUserInput, payload) {
		return nil, httpx.HTTPError(http.StatusInternalServerError, "Failed to submit input to workflow")
	}
	sort.Strings(answerKeys)
	sort.Strings(keys)
	return wirejson.Object{
		{Key: "status", Value: "accepted"}, {Key: "task_id", Value: t.ID},
		{Key: "input_request_id", Value: in.InputRequestID},
		{Key: "answer_keys", Value: answerKeys}, {Key: "secret_keys", Value: keys},
	}, nil
}

// plain is a wirejson value as encoding/json values, for a workflow payload.
func plain(v any) any {
	switch v := v.(type) {
	case wirejson.Object:
		m := make(map[string]any, len(v))
		for _, mem := range v {
			m[mem.Key] = plain(mem.Value)
		}
		return m
	case []any:
		out := make([]any, len(v))
		for i, x := range v {
			out[i] = plain(x)
		}
		return out
	case wirejson.Float:
		return float64(v)
	}
	return v
}

// Command is TaskCommandPayload.
type Command struct {
	Command         string
	ModelInstanceID *string
	BudgetUSD       *money.Decimal
	Message         *string
	MessageID       *string
}

// ErrResumeUnavailable: continuing a closed conversation in a new run needs
// the run launcher, which this process was not given.
var ErrResumeUnavailable = errors.New("continuing a closed conversation is not available")

// ErrModelsUnavailable: change_model needs the models module's resolver.
var ErrModelsUnavailable = errors.New("change_model needs the models resolver, which this process was not given")

func stoppedStatuses(s string) bool { return s == "cancelled" || s == "failed" }

// SendCommand is send_task_command.
func (s *Surface) SendCommand(ctx context.Context, agentID, taskID string, cmd Command) (wirejson.Object, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if cmd.Command == api.CommandUpdateBudget {
		if err := refuseAgentHTTP(c); err != nil {
			return nil, err
		}
	}
	if err := s.requireAgent(ctx, c.Workspace, agentID); err != nil {
		return nil, err
	}
	t, err := s.taskOfAgent(ctx, c.Workspace, agentID, taskID)
	if err != nil {
		return nil, err
	}
	execID := t.executionID()
	var delivered bool
	switch cmd.Command {
	case api.CommandChangeModel:
		if cmd.ModelInstanceID == nil || *cmd.ModelInstanceID == "" {
			return nil, httpx.HTTPError(http.StatusBadRequest, "model_instance_id is required for change_model")
		}
		delivered, err = s.changeModel(ctx, c, t, *cmd.ModelInstanceID)
		if err != nil {
			return nil, err
		}
	case api.CommandQueueMessage:
		if cmd.Message == nil || *cmd.Message == "" {
			return nil, httpx.HTTPError(http.StatusBadRequest, "message is required for queue_message")
		}
		delivered, err = s.queueFollowUp(ctx, c, t, *cmd.Message)
		if err != nil {
			return nil, err
		}
	case api.CommandRemoveMessage:
		if cmd.MessageID == nil || *cmd.MessageID == "" {
			return nil, httpx.HTTPError(http.StatusBadRequest, "message_id is required for remove_message")
		}
		delivered = s.command(ctx, execID, api.CommandRemoveMessage, map[string]any{"message_id": *cmd.MessageID})
	case api.CommandUpdateBudget:
		if cmd.BudgetUSD == nil {
			return nil, httpx.HTTPError(http.StatusBadRequest, "budget_usd is required for update_budget")
		}
		delivered = s.command(ctx, execID, api.CommandUpdateBudget, map[string]any{"budget_usd": *cmd.BudgetUSD})
	default:
		return nil, httpx.HTTPError(http.StatusBadRequest, "Unknown command: "+cmd.Command)
	}
	if !delivered {
		return nil, httpx.HTTPError(http.StatusConflict, "Task is not running; the command could not be delivered to its workflow.")
	}
	return wirejson.Object{{Key: "status", Value: "accepted"}, {Key: "command", Value: cmd.Command}}, nil
}

// messageSender is message_sender: who a queued message is from.
func messageSender(c authn.Caller) map[string]any {
	if c.Subject != nil && c.Subject.Kind == authn.SubjectAgent {
		return map[string]any{"type": "agent", "id": c.Subject.ID}
	}
	return map[string]any{"type": "user", "id": c.UserID}
}

// queueFollowUp is TaskService.queue_follow_up: a live run takes the message;
// a closed conversation continues in a new run.
func (s *Surface) queueFollowUp(ctx context.Context, c authn.Caller, t Task, message string) (bool, error) {
	if t.ExecutionID == nil || *t.ExecutionID == "" {
		return false, nil
	}
	sender := messageSender(c)
	if !stoppedStatuses(t.Status) &&
		s.command(ctx, *t.ExecutionID, api.CommandQueueMessage, map[string]any{"message": message, "sender": sender}) {
		return true, nil
	}
	if t.Status != "completed" && !stoppedStatuses(t.Status) {
		return false, nil
	}
	return s.continueClosed(ctx, c, t, &message, sender)
}

const runStillClosing = "The task is still stopping: it is recording the call it interrupted. Send this again in a few seconds."

// ListEscalations is list_pending_escalations.
func (s *Surface) ListEscalations(ctx context.Context, agentID, taskID string) ([]any, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	t, err := s.taskOfAgent(ctx, c.Workspace, agentID, taskID)
	if err != nil {
		return nil, err
	}
	mayAct, err := s.mayAct(ctx, c, t)
	if err != nil {
		return nil, err
	}
	pending, err := s.pendingEscalations(ctx, t.executionID())
	if errors.Is(err, errWorkflowNotFound) {
		return nil, notFound("Task has no workflow")
	}
	if err != nil {
		return nil, err
	}
	shown := []any{}
	for _, e := range pending {
		if mayResolve(c, e.Approvers, mayAct) {
			args := e.ToolArgs
			if args == nil {
				args = map[string]any{}
			}
			shown = append(shown, wirejson.Object{
				{Key: "escalation_id", Value: e.EscalationID}, {Key: "tool_name", Value: e.ToolName},
				{Key: "tool_call_id", Value: e.ToolCallID}, {Key: "tool_args", Value: args},
			})
		}
	}
	if !mayAct && len(shown) == 0 {
		return nil, httpx.HTTPError(http.StatusForbidden, "You may not act on this task")
	}
	return shown, nil
}

// mayResolve is may_resolve_escalation; an agent never resolves one.
func mayResolve(c authn.Caller, approvers []string, mayAct bool) bool {
	if len(approvers) > 0 {
		return callerCanApprove(c, approvers)
	}
	return mayAct && !c.ActsAsAgent()
}

// callerCanApprove is CallerCanApprove for a person; an agent never approves.
func callerCanApprove(c authn.Caller, approvers []string) bool {
	return !c.ActsAsAgent() && domain.CallerCanApprove(approvers, c.UserID)
}

// Resolution is EscalationResolution.
type Resolution struct {
	EscalationID string
	Approved     bool
	Comment      string
}

// ResolveEscalation is resolve_task_escalation.
func (s *Surface) ResolveEscalation(ctx context.Context, agentID, taskID string, r Resolution) (wirejson.Object, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := refuseAgentHTTP(c); err != nil {
		return nil, err
	}
	if err := s.requireAgent(ctx, c.Workspace, agentID); err != nil {
		return nil, err
	}
	t, err := s.taskOfAgent(ctx, c.Workspace, agentID, taskID)
	if err != nil {
		return nil, err
	}
	execID := t.executionID()
	mayAct, err := s.mayAct(ctx, c, t)
	if err != nil {
		return nil, err
	}
	notPending := httpx.HTTPError(http.StatusNotFound, "Escalation not found or no longer pending")
	if !mayAct {
		pending, err := s.pendingEscalations(ctx, execID)
		if errors.Is(err, errWorkflowNotFound) {
			return nil, notPending
		}
		if err != nil {
			return nil, err
		}
		e, ok := findEscalation(pending, r.EscalationID)
		if !ok {
			return nil, notPending
		}
		if !mayResolve(c, e.Approvers, false) {
			return nil, httpx.HTTPError(http.StatusForbidden, "You are not an approver of this escalation")
		}
	}
	pending, err := s.pendingEscalations(ctx, execID)
	if errors.Is(err, errWorkflowNotFound) {
		return nil, notPending
	}
	if err != nil {
		s.d.Log.ErrorContext(ctx, "Failed to read pending escalations of workflow", "workflow_id", execID, "error", err.Error())
		return nil, httpx.HTTPError(http.StatusInternalServerError, "Failed to resolve escalation")
	}
	e, ok := findEscalation(pending, r.EscalationID)
	if !ok {
		return nil, notPending
	}
	if !callerCanApprove(c, e.Approvers) {
		return nil, httpx.HTTPError(http.StatusForbidden, "You are not an approver of this escalation")
	}
	sig := api.ResolveEscalationSignal{EscalationID: r.EscalationID, Approved: r.Approved, Comment: r.Comment, ResolvedBy: c.UserID}
	if !s.signal(ctx, execID, api.SignalResolveEscalation, sig) {
		return nil, httpx.HTTPError(http.StatusInternalServerError, "Failed to resolve escalation")
	}
	return wirejson.Object{
		{Key: "status", Value: "resolved"}, {Key: "escalation_id", Value: r.EscalationID}, {Key: "approved", Value: r.Approved},
	}, nil
}

func findEscalation(pending []api.PendingEscalationView, id string) (api.PendingEscalationView, bool) {
	for _, e := range pending {
		if e.EscalationID == id {
			return e, true
		}
	}
	return api.PendingEscalationView{}, false
}
