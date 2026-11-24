package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
)

// ResumeSpec continues a closed conversation in a new run of the task's
// workflow (AgentExecutionResume), with the message that reopened it.
type ResumeSpec struct {
	NextSeq             int64
	CurrentIteration    int
	ToolCallsUsed       int
	TokensUsed          int64
	LastPromptTokens    int64
	TotalCost           money.Decimal
	OwnCost             *money.Decimal
	LLMCost             money.Decimal
	SystemPromptMissing bool
	Retry               bool
	Message             *string
	Sender              map[string]any
}

// RunResumer starts a new run of a closed task's workflow
// (TemporalTaskManager.resume_task); the message, when set, is its first signal.
type RunResumer interface {
	Resume(ctx context.Context, workspaceID string, t store.StoredTask, r ResumeSpec) error
}

// ResumeMounted is whether a closed conversation can continue in a new run.
func (s *Surface) ResumeMounted() bool { return s.CreateMounted() && s.d.Resumer != nil }

// continueClosed is _continue_closed_conversation: false when the task's run
// cannot continue; a 409 while a stopped run still closes.
func (s *Surface) continueClosed(ctx context.Context, c authn.Caller, t Task, message *string, sender map[string]any) (bool, error) {
	if v, _ := t.Metadata.Get("created_via"); v == "agent_delegation" || t.ExecutionID == nil || *t.ExecutionID == "" {
		return false, nil
	}
	if s.d.Resumer == nil {
		return false, s.internal(ctx, "Failed to continue the conversation", ErrResumeUnavailable)
	}
	st := s.workflowStatus(ctx, *t.ExecutionID)
	exec := st.ExecutionStatus
	if exec == "" {
		exec = st.Status
	}
	if !closedExecutionStatuses(exec) && exec != "unknown" {
		if stoppedStatuses(t.Status) && exec == "running" {
			return false, httpx.HTTPError(http.StatusConflict, runStillClosing)
		}
		return false, nil
	}
	def, err := s.definition(ctx, c.Workspace, t.AgentID)
	if err != nil && !errors.Is(err, api.ErrAgentNotFound) {
		return false, err
	}
	if err == nil && def.Archived {
		return false, httpx.HTTPError(http.StatusConflict, fmt.Sprintf("Agent %s is archived; restore it first", t.AgentID))
	}
	if err := s.refreshGovernance(ctx, c.Workspace, t); err != nil {
		return false, err
	}
	spec, err := s.conversationResume(ctx, c.Workspace, t)
	if err != nil {
		return false, err
	}
	spec.Retry = message == nil
	spec.Message, spec.Sender = message, sender
	var stored store.StoredTask
	if err := s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, tx db.Session) (err error) {
		stored, err = store.Runs{}.TaskToLaunch(ctx, tx, t.ID)
		return err
	}); err != nil {
		return false, err
	}
	if err := s.d.Resumer.Resume(ctx, c.Workspace.ID(), stored, spec); err != nil {
		return false, err
	}
	if err := s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, tx db.Session) error {
		ok, err := store.SetSurfaceTaskStatus(ctx, tx, t.ID, "running", "", s.d.Now())
		if err == nil && !ok {
			err = fmt.Errorf("task %s not found", t.ID)
		}
		return err
	}); err != nil {
		return false, err
	}
	return true, nil
}

func provenanceUser(p Provenance) string {
	if p.SourceIdentity == nil {
		return ""
	}
	return sourceUserID(api.TaskProvenance{SourceIdentity: *p.SourceIdentity})
}

func snapshotOf(meta wirejson.Object) wirejson.Object {
	v, _ := meta.Get("governance_snapshot")
	o, _ := v.(wirejson.Object)
	return o
}

func revisionOf(snap wirejson.Object) int {
	v, _ := snap.Get("revision")
	if n, ok := v.(json.Number); ok {
		if i, err := n.Int64(); err == nil && i > 0 {
			return int(i)
		}
	}
	return 1
}

func requestedPolicy(snap wirejson.Object) (governanceapi.Policy, error) {
	v, _ := snap.Get("requested_policy")
	if v == nil {
		v = wirejson.Object{}
	}
	p, errs := governanceapi.ParsePolicy(v, nil, false)
	if len(errs) > 0 {
		return governanceapi.Policy{}, fmt.Errorf("stored requested policy does not validate: %s", errs[0].Msg)
	}
	return p, nil
}

func policyRefusal(err error) error {
	if errors.Is(err, governanceapi.ErrPolicyRefused) {
		return httpx.HTTPError(http.StatusUnprocessableEntity, "Task policy rejected").Wrap(err)
	}
	return err
}

// refreshGovernance is _refresh_governance_snapshot: the stored request
// resolved again under today's layers and caps, as the next revision.
func (s *Surface) refreshGovernance(ctx context.Context, ws scope.Workspace, t Task) error {
	snap := snapshotOf(t.Metadata)
	req, err := requestedPolicy(snap)
	if err != nil {
		return err
	}
	effective, next, err := s.d.Policies.Task(ctx, governanceapi.RunPrincipal{Workspace: ws, UserID: provenanceUser(t.Provenance), AgentID: t.AgentID},
		governanceapi.TaskRequest{TaskPolicy: &req})
	if err != nil {
		return policyRefusal(err)
	}
	if err := s.enforceBudget(ctx, ws, effective.Budget, t.AgentID); err != nil {
		var r *Refusal
		if errors.As(err, &r) {
			return r.HTTP()
		}
		return err
	}
	next.Revision = revisionOf(snap) + 1
	return s.d.DB.Write(ctx, ws, func(ctx context.Context, tx db.Session) error {
		ok, err := store.Runs{}.MergeMetadata(ctx, tx, t.ID, map[string]any{"governance_snapshot": next.Stored()}, s.d.Now())
		if err == nil && !ok {
			err = fmt.Errorf("task %s not found", t.ID)
		}
		return err
	})
}

func moneyOf(v any) (money.Decimal, bool) {
	switch x := v.(type) {
	case json.Number:
		d, err := money.Parse(string(x))
		return d, err == nil
	case wirejson.Float:
		d, err := money.Parse(wirejson.FormatFloat(float64(x)))
		return d, err == nil
	case string:
		d, err := money.Parse(x)
		return d, err == nil
	}
	return money.Decimal{}, false
}

func intField(o wirejson.Object, key string) int64 {
	v, _ := o.Get(key)
	if n, ok := v.(json.Number); ok {
		i, _ := n.Int64()
		return i
	}
	return 0
}

// conversationResume is _conversation_resume: the stored snapshot when the
// log still ends where it does, else one rebuilt from the log.
func (s *Surface) conversationResume(ctx context.Context, ws scope.Workspace, t Task) (ResumeSpec, error) {
	var spec ResumeSpec
	result, _ := t.Result.(wirejson.Object)
	if v, _ := result.Get("total_cost"); truthy(v) {
		spec.TotalCost, _ = moneyOf(v)
	}
	if v, _ := result.Get("own_cost"); v != nil {
		if d, ok := moneyOf(v); ok {
			spec.OwnCost = &d
		}
	}
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return spec, err
	}
	raw, err := store.Runs{}.SumSpendSince(ctx, sess, time.Unix(0, 0).UTC(), s.d.Currency(), store.SpendScope{TaskID: t.ID, Category: domain.CostModel})
	if err == nil {
		spec.LLMCost, err = money.Parse(raw)
	}
	var outline []store.OutlineEntry
	if err == nil {
		outline, err = store.ConversationOutline(ctx, sess, t.ID)
	}
	release()
	if err != nil {
		return spec, err
	}
	logEnd := int64(0)
	if len(outline) > 0 {
		logEnd = outline[len(outline)-1].Seq + 1
	}
	if v, _ := t.Metadata.Get("conversation_resume"); v != nil {
		if snap, ok := v.(wirejson.Object); ok {
			next := intField(snap, "next_seq")
			if next == logEnd || (next < logEnd && !messagesFrom(outline, next)) {
				spec.NextSeq = logEnd
				spec.CurrentIteration = int(intField(snap, "current_iteration"))
				spec.ToolCallsUsed = int(intField(snap, "tool_calls_used"))
				spec.TokensUsed = intField(snap, "tokens_used")
				spec.LastPromptTokens = intField(snap, "last_prompt_tokens")
				return spec, nil
			}
			s.d.Log.WarnContext(ctx, "Task resume snapshot ends where its log does not; rebuilding", "task_id", t.ID, "next_seq", next)
		}
	}
	var response string
	if v, _ := result.Get("response"); v != nil {
		response, _ = v.(string)
	}
	rebuilt := reconstruct(outline, t.Description, response)
	if len(rebuilt.appended) > 0 {
		if err := s.d.DB.Write(ctx, ws, func(ctx context.Context, tx db.Session) error {
			ref, err := store.Runs{}.Task(ctx, tx, t.ID)
			if err != nil {
				return err
			}
			for _, e := range rebuilt.appended {
				e.EventID = store.NewEventID()
				if err := (store.Runs{}).InsertEntry(ctx, tx, ref, e, t.CreatedBy); err != nil {
					return err
				}
			}
			return nil
		}); err != nil {
			return spec, err
		}
	}
	spec.NextSeq, spec.CurrentIteration, spec.ToolCallsUsed = rebuilt.nextSeq, rebuilt.iteration, rebuilt.toolCalls
	spec.SystemPromptMissing = rebuilt.systemMissing
	return spec, nil
}

func messagesFrom(outline []store.OutlineEntry, seq int64) bool {
	for _, e := range outline {
		if e.Seq >= seq && e.Kind != "event" {
			return true
		}
	}
	return false
}

type rebuiltConversation struct {
	nextSeq              int64
	iteration, toolCalls int
	appended             []domain.Entry
	systemMissing        bool
}

// reconstruct is reconstruct_conversation over the log's outline.
func reconstruct(outline []store.OutlineEntry, query, response string) rebuiltConversation {
	next := int64(0)
	if len(outline) > 0 {
		next = outline[len(outline)-1].Seq + 1
	}
	log := append([]store.OutlineEntry{}, outline...)
	var out rebuiltConversation
	hasMessage := false
	for _, e := range outline {
		if e.Kind != "event" {
			hasMessage = true
			break
		}
	}
	if !hasMessage {
		out.appended = append(out.appended, domain.Entry{Seq: next, Kind: "message", Role: "user", Content: query})
		log = append(log, store.OutlineEntry{Seq: next, Kind: "message", Role: "user"})
		next++
	}
	var last store.OutlineEntry
	for i := len(log) - 1; i >= 0; i-- {
		if log[i].Kind != "event" {
			last = log[i]
			break
		}
	}
	if response != "" && (last.Role != "assistant" || last.ToolCalls > 0) {
		out.appended = append(out.appended, domain.Entry{Seq: next, Kind: "message", Role: "assistant", Content: response})
		log = append(log, store.OutlineEntry{Seq: next, Kind: "message", Role: "assistant"})
		next++
	}
	out.systemMissing = true
	turns := 0
	for _, e := range log {
		if e.Role == "system" {
			out.systemMissing = false
		}
		if e.Role == "assistant" {
			turns++
			out.toolCalls += e.ToolCalls
		}
	}
	out.nextSeq, out.iteration = next, max(turns, 1)
	return out
}

// Retry is retry_agent_task: a failed task's last turn again, in a new run.
func (s *Surface) Retry(ctx context.Context, agentID, taskID string) (wirejson.Object, error) {
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
	retried := false
	if t.Status == "failed" && t.ExecutionID != nil && *t.ExecutionID != "" {
		if retried, err = s.continueClosed(ctx, c, t, nil, nil); err != nil {
			return nil, err
		}
	}
	if !retried {
		return nil, httpx.HTTPError(http.StatusConflict, "Only a failed task whose run has finished can be retried.")
	}
	return wirejson.Object{
		{Key: "status", Value: "running"}, {Key: "task_id", Value: t.ID}, {Key: "execution_id", Value: "task-" + t.ID},
	}, nil
}

// Continuation is ContinueTaskPayload.
type Continuation struct {
	Iterations, Tokens, ToolCalls int64
	Budget                        *money.Decimal
}

// continuationGrantRequired is _CONTINUATION_GRANT_REQUIRED: the grant a
// limit's stop needs, "" for a stop no grant answers.
func continuationGrantRequired(stopped string) string {
	switch stopped {
	case "iteration_limit":
		return "additional_iterations_required"
	case "budget_exceeded":
		return "additional_budget_required"
	case "token_limit":
		return "additional_tokens_required"
	case "tool_call_limit":
		return "additional_tool_calls_required"
	}
	return ""
}

func notAccepted(reason string) error {
	return httpx.HTTPError(http.StatusConflict, "Continuation was not accepted").With("reason", reason)
}

// ContinueExecution is continue_task_execution: a run waiting on a limit
// granted more, under a policy resolved again with the grant as its request.
func (s *Surface) ContinueExecution(ctx context.Context, taskID string, g Continuation) (any, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := refuseAgentHTTP(c); err != nil {
		return nil, err
	}
	if g.Iterations == 0 && g.Budget == nil && g.Tokens == 0 && g.ToolCalls == 0 {
		return nil, httpx.HTTPError(http.StatusUnprocessableEntity, "At least one continuation resource must be granted")
	}
	t, ok, err := s.loadTask(ctx, c.Workspace, taskID)
	if err != nil {
		return nil, s.internal(ctx, "Failed to continue the task", err)
	}
	if !ok {
		return nil, notFound("Task not found")
	}
	if t.Status != "waiting_for_continuation" {
		return nil, notAccepted("not_waiting_for_continuation")
	}
	if t.ExecutionID == nil || *t.ExecutionID == "" {
		return nil, notAccepted("workflow_unavailable")
	}
	snap := snapshotOf(t.Metadata)
	effRaw, _ := snap.Get("effective_policy")
	if !governanceapi.IsObject(effRaw) {
		return nil, notAccepted("governance_snapshot_missing")
	}
	current, errs := governanceapi.ParsePolicy(effRaw, nil, true)
	if len(errs) > 0 || current.RequireRuntimeContract() != nil {
		return nil, notAccepted("governance_snapshot_missing")
	}
	granted := map[string]bool{
		"iteration_limit": g.Iterations > 0, "budget_exceeded": g.Budget != nil,
		"token_limit": g.Tokens > 0, "tool_call_limit": g.ToolCalls > 0,
	}
	if stopped, _ := t.Metadata.Get("failure_reason"); stopped != nil {
		if reason := continuationGrantRequired(fmt.Sprint(stopped)); reason != "" && !granted[fmt.Sprint(stopped)] {
			return nil, notAccepted(reason)
		}
	}
	req, err := requestedPolicy(snap)
	if err != nil {
		return nil, s.internal(ctx, "Failed to continue the task", err)
	}
	grow(&req, current, g)
	effective, next, err := s.d.Policies.Task(ctx, governanceapi.RunPrincipal{Workspace: c.Workspace, UserID: provenanceUser(t.Provenance), AgentID: t.AgentID},
		governanceapi.TaskRequest{TaskPolicy: &req})
	if errors.Is(err, governanceapi.ErrPolicyRefused) {
		return nil, notAccepted("policy_ceiling")
	}
	if err != nil {
		return nil, s.internal(ctx, "Failed to continue the task", err)
	}
	if err := s.enforceBudget(ctx, c.Workspace, effective.Budget, t.AgentID); err != nil {
		var r *Refusal
		if errors.As(err, &r) {
			return nil, r.HTTP()
		}
		return nil, s.internal(ctx, "Failed to continue the task", err)
	}
	if effective.Execution == nil {
		return nil, notAccepted("governance_snapshot_missing")
	}
	next.Revision = revisionOf(snap) + 1
	payload := api.ContinueExecution{
		AdditionalIterations: int(g.Iterations), AdditionalBudget: g.Budget,
		AdditionalTokens: int(g.Tokens), AdditionalToolCalls: int(g.ToolCalls),
	}
	if payload.Policy, payload.Governance, err = runsPolicy(effective, next); err != nil {
		return nil, s.internal(ctx, "Failed to continue the task", err)
	}
	var out api.ContinueExecutionResult
	if err := s.d.Executor.Update(ctx, *t.ExecutionID, api.UpdateContinueExecution, &out, payload); err != nil {
		s.d.Log.ErrorContext(ctx, "Failed to continue the workflow", "task_id", t.ID, "error", err.Error())
		return nil, notAccepted("workflow_unavailable")
	}
	if !out.Accepted {
		reason := out.Reason
		if reason == "" {
			reason = "continuation_rejected"
		}
		return nil, notAccepted(reason)
	}
	return out, nil
}

// grow is continue_execution's request: each granted limit raised from the
// one the run stopped under.
func grow(req *governanceapi.Policy, current governanceapi.Policy, g Continuation) {
	if g.Iterations > 0 || g.ToolCalls > 0 {
		x := governanceapi.Execution{}
		if req.Execution != nil {
			x = *req.Execution
		}
		if g.Iterations > 0 {
			v := *current.Execution.MaxModelTurns + g.Iterations
			x.MaxModelTurns = &v
		}
		if g.ToolCalls > 0 {
			v := *current.Execution.MaxToolCallsTotal + g.ToolCalls
			x.MaxToolCallsTotal = &v
		}
		req.Execution = &x
	}
	if g.Tokens > 0 {
		t := governanceapi.Tokens{}
		if req.Tokens != nil {
			t = *req.Tokens
		}
		v := *current.Tokens.MaxTokens + g.Tokens
		t.MaxTokens = &v
		req.Tokens = &t
	}
	if g.Budget != nil {
		b := governanceapi.Budget{}
		if req.Budget != nil {
			b = *req.Budget
		}
		v := current.Budget.RunBudgetUSD.Add(*g.Budget)
		b.RunBudgetUSD = &v
		req.Budget = &b
	}
}

// runsPolicy is the resolved policy and snapshot as the workflow reads them.
func runsPolicy(p governanceapi.Policy, snap governanceapi.Snapshot) (*api.Policy, *api.GovernanceSnapshot, error) {
	var pol api.Policy
	var gs api.GovernanceSnapshot
	raw, err := json.Marshal(p)
	if err != nil {
		return nil, nil, err
	}
	if err := json.Unmarshal(raw, &pol); err != nil {
		return nil, nil, err
	}
	if raw, err = json.Marshal(snap); err != nil {
		return nil, nil, err
	}
	if err := json.Unmarshal(raw, &gs); err != nil {
		return nil, nil, err
	}
	return &pol, &gs, nil
}

// changeModel is _resolve_model_info then the change_model command.
func (s *Surface) changeModel(ctx context.Context, c authn.Caller, t Task, instanceID string) (bool, error) {
	if s.d.Models == nil {
		return false, s.internal(ctx, "Failed to send command", ErrModelsUnavailable)
	}
	m, err := s.d.Models.Model(ctx, modelsapi.Principal{WorkspaceID: c.Workspace.ID(), UserID: c.UserID, AgentID: t.AgentID}, instanceID)
	switch {
	case errors.Is(err, modelsapi.ErrNotFound):
		return false, notFound("Model instance not found")
	case errors.Is(err, modelsapi.ErrRefused):
		return false, httpx.HTTPError(http.StatusConflict, "Model instance cannot run a task: "+err.Error())
	case err != nil:
		return false, s.internal(ctx, "Failed to send command", err)
	}
	raw, err := json.Marshal(m)
	if err != nil {
		return false, s.internal(ctx, "Failed to send command", err)
	}
	var model map[string]any
	if err := json.Unmarshal(raw, &model); err != nil {
		return false, s.internal(ctx, "Failed to send command", err)
	}
	return s.command(ctx, t.executionID(), api.CommandChangeModel, map[string]any{"model": model, "changed_by": messageSender(c)}), nil
}
