package service

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
)

// PlatformRuns is api.PlatformRuns over the surface: the runs toolset's
// control tools take only a run id, so each loads the run in the caller's
// workspace first and applies the run authority the REST routes apply.
type PlatformRuns struct{ s *Surface }

var _ api.PlatformRuns = PlatformRuns{}

// PlatformRuns is the runs toolset's provider.
func (s *Surface) PlatformRuns() PlatformRuns { return PlatformRuns{s: s} }

// toolRefusal is a refusal in the words the toolset reports.
type toolRefusal string

func (r toolRefusal) Error() string { return string(r) }

const (
	runNotFound        = "Run not found"
	runStillStopping   = "The run is still stopping; try again in a few seconds"
	notWorkspaceAdmin  = "Only a workspace admin may perform this action"
	escalationGone     = "Escalation not found or no longer pending"
	notAnApprover      = "You are not an approver of this escalation"
	runDescriptionMax  = 20000
	inputRequestIDMax  = 128
	maxGrantIterations = 1000
	maxGrantTokens     = 10_000_000
	maxGrantToolCalls  = 10_000
)

// reservedRunParameters are RESERVED_TASK_PARAMETERS, sorted.
func reservedRunParameters() []string {
	return []string{"delivery_address", "follow_up_message", "session", "trigger_event", "trigger_event_file"}
}

// toolText is err as the toolset reports it: a refused requires() is
// "Permission denied", a caller who is not an admin is assert_workspace_admin's 403.
func toolText(err error) error {
	switch {
	case err == nil:
		return nil
	case errors.Is(err, authz.ErrDenied):
		return toolRefusal("Permission denied")
	case errors.Is(err, authz.ErrNotWorkspaceAdmin):
		return toolRefusal(notWorkspaceAdmin)
	}
	return err
}

// task is the run in the caller's workspace; "Run not found" when there is none.
func (p PlatformRuns) task(ctx context.Context, c authn.Caller, runID string) (Task, error) {
	t, ok, err := p.s.loadTask(ctx, c.Workspace, runID)
	if err != nil {
		return Task{}, err
	}
	if !ok {
		return Task{}, errors.New(runNotFound)
	}
	return t, nil
}

// mayActOn is _ensure_may_act: the run, unless the caller neither started it
// nor administers the workspace.
func (p PlatformRuns) mayActOn(ctx context.Context, c authn.Caller, runID string) (Task, error) {
	t, err := p.task(ctx, c, runID)
	if err != nil {
		return Task{}, err
	}
	ok, err := p.s.mayAct(ctx, c, t)
	if err != nil {
		return Task{}, toolText(err)
	}
	if !ok {
		return Task{}, toolRefusal(notWorkspaceAdmin)
	}
	return t, nil
}

// pyStrTime is str(datetime) of an aware datetime, as json.dumps(default=str) writes it.
func pyStrTime(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/1000 != 0 {
		return t.Format("2006-01-02 15:04:05.000000-07:00")
	}
	return t.Format("2006-01-02 15:04:05-07:00")
}

// runCreate is RunCreate's validation of the toolset's arguments.
func runCreate(in api.RunStart, now time.Time) (map[string]any, *time.Time, error) {
	if _, err := uuid.Parse(in.AgentID); err != nil {
		return nil, nil, errors.New("agent_id: Input should be a valid UUID")
	}
	switch n := utf8.RuneCountInString(in.Description); {
	case n < 1:
		return nil, nil, errors.New("description: String should have at least 1 character")
	case n > runDescriptionMax:
		return nil, nil, fmt.Errorf("description: String should have at most %d characters", runDescriptionMax)
	}
	params := map[string]any{}
	for k, v := range in.Parameters {
		params[k] = v
	}
	var hit []string
	for _, k := range reservedRunParameters() {
		if _, ok := params[k]; ok {
			hit = append(hit, k)
		}
	}
	if len(hit) > 0 {
		return nil, nil, errors.New("parameters: " + strings.Join(hit, ", ") + " is set by the trigger that received the event and cannot be supplied")
	}
	if mo, ok := params["model_override"]; ok && mo != nil && mo != "" {
		s, isStr := mo.(string)
		if _, err := uuid.Parse(s); !isStr || err != nil {
			return nil, nil, errors.New("parameters: model_override must be a model instance id")
		}
	}
	if in.ScheduledAt == nil {
		return params, nil, nil
	}
	at, err := time.Parse(time.RFC3339Nano, *in.ScheduledAt)
	if err != nil {
		if _, naive := time.Parse("2006-01-02T15:04:05.999999999", *in.ScheduledAt); naive == nil {
			return nil, nil, errors.New("scheduled_at: scheduled_at must include a UTC offset")
		}
		return nil, nil, errors.New("scheduled_at: Input should be a valid datetime")
	}
	if !at.After(now) {
		return nil, nil, errors.New("scheduled_at: scheduled_at must be in the future")
	}
	return params, &at, nil
}

func (p PlatformRuns) Start(ctx context.Context, c authn.Caller, in api.RunStart) (api.RunStarted, error) {
	ctx = authn.WithCaller(ctx, c)
	if _, err := uuid.Parse(in.AgentID); err != nil {
		return api.RunStarted{}, errors.New("agent_id must be a UUID")
	}
	if !p.s.CreateMounted() {
		return api.RunStarted{}, errors.New("starting a run needs the run policies and the launcher, which this process was not given")
	}
	if err := p.s.d.Permissions(ctx, c, "execute", "agent", in.AgentID); err != nil {
		return api.RunStarted{}, toolText(err)
	}
	params, scheduled, err := runCreate(in, p.s.d.Now())
	if err != nil {
		return api.RunStarted{}, err
	}
	meta := map[string]any{"created_via": "mcp"}
	if in.ProjectID != nil {
		meta["project_id"] = *in.ProjectID
	}
	sp := runSpec{
		TaskID: uuid.NewString(), AgentID: in.AgentID, Description: in.Description, Parameters: params,
		UserID: c.UserID, RequiresHumanApproval: in.RequiresHumanApproval, Metadata: meta,
		Provenance: provenanceOf(c), ScheduledAt: scheduled, Credential: c.Credential,
	}
	if err := p.s.start(ctx, c.Workspace, sp); err != nil {
		return api.RunStarted{}, err
	}
	t, err := p.task(ctx, c, sp.TaskID)
	if err != nil {
		return api.RunStarted{}, err
	}
	out := api.RunStarted{RunID: t.ID, Status: t.Status}
	if t.ScheduledAt != nil {
		at := pyStrTime(*t.ScheduledAt)
		out.ScheduledAt = &at
	}
	return out, nil
}

func agentOf(t Task) *string {
	if t.AgentID == "" || t.AgentID == uuid.Nil.String() {
		return nil
	}
	id := t.AgentID
	return &id
}

func (p PlatformRuns) List(ctx context.Context, c authn.Caller, agentID string, limit int) ([]api.RunSummary, error) {
	var agent uuid.UUID
	if agentID != "" {
		u, err := uuid.Parse(agentID)
		if err != nil {
			return nil, errors.New("agent_id must be a UUID")
		}
		agent = u
	}
	sess, release, err := p.s.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return nil, err
	}
	defer release()
	q := store.New(sess.Q())
	var rows []store.SurfaceTaskRow
	if agentID != "" {
		got, err := q.SurfaceAgentTasks(ctx, store.SurfaceAgentTasksParams{
			WorkspaceID: c.Workspace.ID(), AgentID: agent, Status: store.Text(nil), MaxRows: int32(limit), //nolint:gosec // bounded by the tool
		})
		if err != nil {
			return nil, err
		}
		for _, r := range got {
			rows = append(rows, store.SurfaceTaskRow(r))
		}
	} else {
		got, err := q.SurfaceTaskPage(ctx, store.SurfaceTaskPageParams{
			WorkspaceID: c.Workspace.ID(), Statuses: []string{}, CreatedBy: store.Text(nil), Search: store.Text(nil),
			SearchAgentIds: []uuid.UUID{}, MaxRows: int32(limit), //nolint:gosec // bounded by the tool
		})
		if err != nil {
			return nil, err
		}
		for _, r := range got {
			rows = append(rows, store.SurfaceTaskRow(r))
		}
	}
	out := make([]api.RunSummary, 0, len(rows))
	for _, r := range rows {
		t, err := taskOf(r)
		if err != nil {
			return nil, err
		}
		out = append(out, api.RunSummary{RunID: t.ID, Title: t.Description, Status: t.Status, AgentID: agentOf(t)})
	}
	return out, nil
}

func (p PlatformRuns) Get(ctx context.Context, c authn.Caller, runID string) (api.RunDetail, error) {
	t, err := p.task(ctx, c, runID)
	if err != nil {
		return api.RunDetail{}, err
	}
	return api.RunDetail{
		RunSummary: api.RunSummary{RunID: t.ID, Title: t.Description, Status: t.Status, AgentID: agentOf(t)},
		Query:      t.Description, Provenance: provenanceJSON(t.Provenance),
	}, nil
}

// Cancel is TemporalTaskManager.cancel_task on the run's own workflow: false
// when the run has ended or its workflow could not be cancelled.
func (p PlatformRuns) Cancel(ctx context.Context, c authn.Caller, runID string) (bool, error) {
	ctx = authn.WithCaller(ctx, c)
	t, err := p.mayActOn(ctx, c, runID)
	if err != nil {
		return false, err
	}
	if uncancellable(t.Status) || t.Status == "completed" {
		return false, nil
	}
	if t.Status == "scheduled" {
		return p.s.cancelScheduled(ctx, c.Workspace, t)
	}
	execID := t.executionID()
	if err := p.s.d.Executor.Cancel(ctx, execID); err != nil {
		p.s.d.Log.ErrorContext(ctx, "Failed to cancel workflow", "workflow_id", execID, "error", err.Error())
		return false, nil
	}
	err = p.s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, tx db.Session) error {
		_, err := store.SetSurfaceTaskStatus(ctx, tx, t.ID, "cancelled", "", p.s.d.Now())
		return err
	})
	if err != nil {
		return false, err
	}
	return true, nil
}

// stillStopping is the toolset's text for a run that is recording the call it interrupted.
func stillStopping(err error) error {
	var he *httpx.Error
	if errors.As(err, &he) && he.Status == http.StatusConflict && he.Detail == runStillClosing {
		return toolRefusal(runStillStopping)
	}
	return err
}

func (p PlatformRuns) Retry(ctx context.Context, c authn.Caller, runID string) error {
	ctx = authn.WithCaller(ctx, c)
	t, err := p.mayActOn(ctx, c, runID)
	if err != nil {
		return err
	}
	retried := false
	if t.Status == "failed" && t.ExecutionID != nil && *t.ExecutionID != "" {
		if retried, err = p.s.continueClosed(ctx, c, t, nil, nil); err != nil {
			return stillStopping(err)
		}
	}
	if !retried {
		return toolRefusal("Only a failed run whose execution has finished can be retried")
	}
	return nil
}

func (p PlatformRuns) Pause(ctx context.Context, c authn.Caller, runID string) (bool, error) {
	ctx = authn.WithCaller(ctx, c)
	t, err := p.mayActOn(ctx, c, runID)
	if err != nil {
		return false, err
	}
	return p.s.signal(ctx, t.executionID(), api.SignalPause, api.PauseSignal{Reason: "User requested pause"}), nil
}

func (p PlatformRuns) Resume(ctx context.Context, c authn.Caller, runID string) (bool, error) {
	ctx = authn.WithCaller(ctx, c)
	t, err := p.mayActOn(ctx, c, runID)
	if err != nil {
		return false, err
	}
	return p.s.signal(ctx, t.executionID(), api.SignalResume, api.PauseSignal{Reason: "User requested resume"}), nil
}

// SendInput is the submit_user_input command; secret answers are not taken here.
func (p PlatformRuns) SendInput(ctx context.Context, c authn.Caller, runID, inputRequestID string, answers map[string]any) (bool, error) {
	ctx = authn.WithCaller(ctx, c)
	if c.ActsAsAgent() {
		return false, toolRefusal(humanOnly)
	}
	switch n := utf8.RuneCountInString(inputRequestID); {
	case n < 1:
		return false, errors.New("input_request_id: String should have at least 1 character")
	case n > inputRequestIDMax:
		return false, fmt.Errorf("input_request_id: String should have at most %d characters", inputRequestIDMax)
	}
	t, err := p.mayActOn(ctx, c, runID)
	if err != nil {
		return false, err
	}
	if answers == nil {
		answers = map[string]any{}
	}
	return p.s.command(ctx, t.executionID(), api.CommandSubmitUserInput, map[string]any{
		"input_request_id": inputRequestID, "answers": answers, "secret_refs": map[string]any{}, "submitted_by": c.UserID,
	}), nil
}

func (p PlatformRuns) SendCommand(ctx context.Context, c authn.Caller, runID string, cmd api.RunCommand) (bool, error) {
	ctx = authn.WithCaller(ctx, c)
	var budget *money.Decimal
	if cmd.BudgetUSD != nil {
		d, err := money.Parse(strings.TrimSpace(*cmd.BudgetUSD))
		if err != nil {
			return false, fmt.Errorf("budget_usd: Value error, %s is not a money amount", domain.PyStrRepr(*cmd.BudgetUSD))
		}
		budget = &d
	}
	if cmd.Command == api.CommandUpdateBudget && c.ActsAsAgent() {
		return false, toolRefusal(humanOnly)
	}
	t, err := p.mayActOn(ctx, c, runID)
	if err != nil {
		return false, err
	}
	empty := func(s *string) bool { return s == nil || *s == "" }
	switch cmd.Command {
	case api.CommandQueueMessage:
		if empty(cmd.Message) {
			return false, errors.New("message is required for queue_message")
		}
		ok, err := p.s.queueFollowUp(ctx, c, t, *cmd.Message)
		return ok, stillStopping(err)
	case api.CommandRemoveMessage:
		if empty(cmd.MessageID) {
			return false, errors.New("message_id is required for remove_message")
		}
		return p.s.command(ctx, t.executionID(), api.CommandRemoveMessage, map[string]any{"message_id": *cmd.MessageID}), nil
	case api.CommandUpdateBudget:
		if budget == nil {
			return false, errors.New("budget_usd is required for update_budget")
		}
		return p.s.command(ctx, t.executionID(), api.CommandUpdateBudget, map[string]any{"budget_usd": *budget}), nil
	case api.CommandChangeModel:
		if empty(cmd.ModelInstanceID) {
			return false, errors.New("model_instance_id is required for change_model")
		}
		return p.s.changeModel(ctx, c, t, *cmd.ModelInstanceID)
	}
	return false, errors.New("Unknown command: " + cmd.Command)
}

// escalationAuthority is _escalation_authority: the run, and whether the caller may act on it.
func (p PlatformRuns) escalationAuthority(ctx context.Context, c authn.Caller, runID string) (Task, bool, error) {
	t, err := p.task(ctx, c, runID)
	if err != nil {
		return Task{}, false, err
	}
	ok, err := p.s.mayAct(ctx, c, t)
	return t, ok, toolText(err)
}

func (p PlatformRuns) ResolveEscalation(ctx context.Context, c authn.Caller, runID, escalationID string, approved bool, comment string) (bool, error) {
	ctx = authn.WithCaller(ctx, c)
	if c.ActsAsAgent() {
		return false, toolRefusal(humanOnly)
	}
	t, mayAct, err := p.escalationAuthority(ctx, c, runID)
	if err != nil {
		return false, err
	}
	execID := t.executionID()
	if !mayAct {
		pending, err := p.s.pendingEscalations(ctx, execID)
		if errors.Is(err, errWorkflowNotFound) {
			return false, toolRefusal(escalationGone)
		}
		if err != nil {
			return false, err
		}
		e, ok := findEscalation(pending, escalationID)
		if !ok {
			return false, toolRefusal(escalationGone)
		}
		if !mayResolve(c, e.Approvers, false) {
			return false, toolRefusal(notAnApprover)
		}
	}
	pending, err := p.s.pendingEscalations(ctx, execID)
	if errors.Is(err, errWorkflowNotFound) {
		return false, toolRefusal(escalationGone)
	}
	if err != nil {
		return false, err
	}
	e, ok := findEscalation(pending, escalationID)
	if !ok {
		return false, toolRefusal(escalationGone)
	}
	if !callerCanApprove(c, e.Approvers) {
		return false, toolRefusal(notAnApprover)
	}
	sig := api.ResolveEscalationSignal{EscalationID: escalationID, Approved: approved, Comment: comment, ResolvedBy: c.UserID}
	return p.s.signal(ctx, execID, api.SignalResolveEscalation, sig), nil
}

func (p PlatformRuns) ListPendingEscalations(ctx context.Context, c authn.Caller, runID string) ([]api.PendingEscalation, error) {
	ctx = authn.WithCaller(ctx, c)
	t, mayAct, err := p.escalationAuthority(ctx, c, runID)
	if err != nil {
		return nil, err
	}
	pending, err := p.s.pendingEscalations(ctx, t.executionID())
	if errors.Is(err, errWorkflowNotFound) {
		return nil, errors.New("Run has no workflow to read escalations from")
	}
	if err != nil {
		return nil, err
	}
	shown := []api.PendingEscalation{}
	for _, e := range pending {
		if !mayResolve(c, e.Approvers, mayAct) {
			continue
		}
		args := e.ToolArgs
		if args == nil {
			args = map[string]any{}
		}
		shown = append(shown, api.PendingEscalation{EscalationID: e.EscalationID, ToolName: e.ToolName, ToolCallID: e.ToolCallID, ToolArgs: args})
	}
	if !mayAct && len(shown) == 0 {
		return nil, toolRefusal("You may not act on this run")
	}
	return shown, nil
}

// grant is ContinueTaskPayload's validation of the toolset's arguments.
func grant(g api.RunGrant) (Continuation, error) {
	for _, b := range []struct {
		name string
		v    int64
		max  int64
	}{{"additional_iterations", g.Iterations, maxGrantIterations}, {"additional_tokens", g.Tokens, maxGrantTokens}, {"additional_tool_calls", g.ToolCalls, maxGrantToolCalls}} {
		if b.v < 0 {
			return Continuation{}, fmt.Errorf("%s: Input should be greater than or equal to 0", b.name)
		}
		if b.v > b.max {
			return Continuation{}, fmt.Errorf("%s: Input should be less than or equal to %d", b.name, b.max)
		}
	}
	out := Continuation{Iterations: g.Iterations, Tokens: g.Tokens, ToolCalls: g.ToolCalls}
	if g.BudgetUSD != nil {
		d, err := money.Parse(strings.TrimSpace(*g.BudgetUSD))
		if err != nil {
			return Continuation{}, fmt.Errorf("additional_budget_usd: Value error, %s is not a money amount", domain.PyStrRepr(*g.BudgetUSD))
		}
		if d.Cmp(money.Decimal{}) <= 0 {
			return Continuation{}, errors.New("additional_budget_usd: Input should be greater than 0")
		}
		out.Budget = &d
	}
	return out, nil
}

// ContinueRun is TaskService.continue_execution: a refusal the run answers is
// {"accepted": false, "reason": ...}, not an error.
func (p PlatformRuns) ContinueRun(ctx context.Context, c authn.Caller, runID string, g api.RunGrant) (api.ContinueExecutionResult, error) {
	ctx = authn.WithCaller(ctx, c)
	if c.ActsAsAgent() {
		return api.ContinueExecutionResult{}, toolRefusal(humanOnly)
	}
	cont, err := grant(g)
	if err != nil {
		return api.ContinueExecutionResult{}, err
	}
	if _, err := p.mayActOn(ctx, c, runID); err != nil {
		return api.ContinueExecutionResult{}, err
	}
	out, err := p.s.ContinueExecution(ctx, runID, cont)
	var he *httpx.Error
	if errors.As(err, &he) && he.Status == http.StatusConflict {
		if reason, ok := he.Extensions.Get("reason"); ok {
			return api.ContinueExecutionResult{Accepted: false, Reason: fmt.Sprint(reason)}, nil
		}
	}
	if err != nil {
		return api.ContinueExecutionResult{}, err
	}
	res, ok := out.(api.ContinueExecutionResult)
	if !ok {
		return api.ContinueExecutionResult{}, fmt.Errorf("continue_execution answered %T", out)
	}
	return res, nil
}

func terminalEventFields() []string {
	return []string{"status", "success", "error", "error_type", "failure_reason", "blocked_reason"}
}
func failureEventFields() []string {
	return []string{"error", "error_type", "failure_reason", "error_detail", "blocked_reason", "model_id"}
}
func toolResultEventFields() []string {
	return []string{"tool_name", "tool_call_id", "success", "replayed", "error", "exit_code"}
}
func modelCallEventFields() []string {
	return []string{"model_id", "model_name", "cost", "provider_cost_usd"}
}
func inputRequestFields() []string {
	return []string{"input_request_id", "tool_call_id", "question", "questions", "allow_custom_response", "input_mode"}
}
func inputResponseFields() []string {
	return []string{"input_request_id", "tool_call_id", "answer_keys", "secret_keys"}
}

func terminalEventType(t string) bool {
	switch t {
	case "task.completed", "task.failed", "task.cancelled", "execution.finished":
		return true
	}
	return strings.HasPrefix(t, "task.awaiting_")
}

// eventProjection is _event_projection: the facts of one event worth reading
// over MCP; revealed adds a tool call's arguments and result.
func eventProjection(eventType string, data wirejson.Object, revealed bool) wirejson.Object {
	var fields []string
	extra := wirejson.Object{}
	if revealed && (eventType == domain.EventToolCall || eventType == domain.EventToolResult) {
		for _, k := range []string{"arguments", "result"} {
			if v, ok := data.Get(k); ok {
				extra.Set(k, v)
			}
		}
	}
	switch {
	case terminalEventType(eventType):
		fields = terminalEventFields()
	case strings.HasSuffix(eventType, ".failed"):
		fields = failureEventFields()
	case eventType == domain.EventToolCall:
		fields = []string{"tool_name", "tool_call_id"}
		if args, ok := data.Get("arguments"); ok {
			if o, isObj := args.(wirejson.Object); isObj && len(o) > 0 {
				names := make([]any, len(o))
				for i, m := range o {
					names[i] = m.Key
				}
				extra.Set("argument_names", names)
			}
		}
	case eventType == domain.EventToolResult:
		fields = toolResultEventFields()
	case eventType == "input.request":
		fields = inputRequestFields()
	case eventType == "input.response":
		fields = inputResponseFields()
	case eventType == "llm.call.completed":
		fields = modelCallEventFields()
		if u, ok := data.Get("usage"); ok {
			if uo, isObj := u.(wirejson.Object); isObj {
				if inner, ok := uo.Get("usage"); ok {
					if io, isObj := inner.(wirejson.Object); isObj && len(io) > 0 {
						extra.Set("usage", io)
					}
				}
			}
		}
	}
	out := wirejson.Object{}
	for _, k := range append([]string{"message"}, fields...) {
		if v, ok := data.Get(k); ok && v != nil {
			out.Set(k, v)
		}
	}
	for _, m := range extra {
		out.Set(m.Key, m.Value)
	}
	return out
}

// Events is the run's persisted events, oldest first, from offset.
func (p PlatformRuns) Events(ctx context.Context, c authn.Caller, runID string, limit, offset int, eventType *string) (api.RunEventsPage, error) {
	ctx = authn.WithCaller(ctx, c)
	id, err := uuid.Parse(runID)
	if err != nil {
		return api.RunEventsPage{}, errors.New("run_id must be a UUID")
	}
	limit, offset = max(limit, 0), max(offset, 0)
	sess, release, err := p.s.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return api.RunEventsPage{}, err
	}
	defer release()
	q := store.New(sess.Q())
	typ := store.Text(nil)
	if eventType != nil && *eventType != "" {
		typ = store.Text(eventType)
	}
	total, err := q.SurfaceFeedCount(ctx, store.SurfaceFeedCountParams{TaskID: id, WorkspaceID: c.Workspace.ID(), EventType: typ})
	if err != nil {
		return api.RunEventsPage{}, err
	}
	got, err := q.SurfaceFeedPage(ctx, store.SurfaceFeedPageParams{
		TaskID: id, WorkspaceID: c.Workspace.ID(), EventType: typ, Skip: int32(offset), MaxRows: int32(limit), //nolint:gosec // bounded by the tool
	})
	if err != nil {
		return api.RunEventsPage{}, err
	}
	rows := make([]feedRow, len(got))
	showsTools := false
	for i, g := range got {
		if rows[i], err = feedRowOf(store.SurfaceFeedAfterRow(g)); err != nil {
			return api.RunEventsPage{}, err
		}
		showsTools = showsTools || rows[i].Name == domain.EventToolCall || rows[i].Name == domain.EventToolResult
	}
	revealed := false
	if showsTools {
		t, ok, err := p.s.loadTask(ctx, c.Workspace, runID)
		if err != nil {
			return api.RunEventsPage{}, err
		}
		if ok {
			if revealed, err = p.s.mayAct(ctx, c, t); err != nil {
				return api.RunEventsPage{}, toolText(err)
			}
		}
	}
	var bodies *feedBodies
	if revealed {
		if bodies, err = readBodies(ctx, q, c.Workspace, id, rows, true); err != nil {
			return api.RunEventsPage{}, err
		}
	}
	events := []any{}
	for _, r := range rows {
		typ, data, ok, err := feedEvent(r, bodies)
		if err != nil {
			return api.RunEventsPage{}, err
		}
		if !ok {
			continue
		}
		var at any
		if r.OccurredAt != nil {
			at = PyISO(*r.OccurredAt, false)
		}
		item := wirejson.Object{
			{Key: "id", Value: r.EventID}, {Key: "seq", Value: r.Seq}, {Key: "event_type", Value: typ}, {Key: "timestamp", Value: at},
		}
		for _, m := range eventProjection(typ, data, revealed) {
			item.Set(m.Key, m.Value)
		}
		events = append(events, item)
	}
	return api.RunEventsPage{Total: total, Events: events}, nil
}
