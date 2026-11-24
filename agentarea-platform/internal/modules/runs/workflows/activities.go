package workflows

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"go.temporal.io/sdk/activity"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/service"
)

// Activities adapt the run's use cases to Temporal: payloads in and out,
// heartbeats, and the runner turn's signals to its run.
type Activities struct {
	svc  *service.Service
	exec durable.Executor
}

// NewActivities is the activity side over the service; exec signals runner turn updates to their run.
func NewActivities(svc *service.Service, exec durable.Executor) *Activities {
	return &Activities{svc: svc, exec: exec}
}

// RegisterActivities registers every activity of steps 1-12 by its spec's name and kind.
func RegisterActivities(w durable.Worker, a *Activities) {
	fns := a.byName()
	for _, spec := range ActivitySpecs() {
		if fn, ok := fns[spec.Name]; ok {
			w.RegisterActivity(durable.Activity{Name: spec.Name, Kind: spec.Kind, Fn: fn})
		}
	}
}

func (a *Activities) byName() map[string]any {
	return map[string]any{
		api.ActivityStoreContextOutput:       a.StoreContextOutput,
		api.ActivityReadContextOutput:        a.ReadContextOutput,
		api.ActivitySearchHistory:            a.SearchHistory,
		api.ActivityRecallHistory:            a.RecallHistory,
		api.ActivityDelegatedTaskSpend:       a.DelegatedTaskSpend,
		api.ActivityCheckMonthlySpendCap:     a.CheckMonthlySpendCap,
		api.ActivityDeliverToRunner:          a.DeliverToRunner,
		api.ActivityValidateArtifacts:        a.ValidateArtifacts,
		api.ActivityResolveRunConfig:         a.ResolveRunConfig,
		api.ActivityUpdateGovernanceSnapshot: a.UpdateGovernanceSnapshot,
		api.ActivityRecord:                   a.Record,
		api.ActivityActivateSkill:            a.ActivateSkill,
		api.ActivityCreateDelegationTask:     a.CreateDelegationTask,
		api.ActivityRunRunnerTurn:            a.RunRunnerTurn,
		api.ActivityCallLLM:                  a.CallLLM,
		api.ActivityCompactMessages:          a.CompactMessages,
		api.ActivityExecuteTool:              a.ExecuteTool,
		api.ActivityGetRemoteTask:            a.GetRemoteTask,
		api.ActivityCancelRemoteTask:         a.CancelRemoteTask,
	}
}

// heartbeatEvery is the heartbeat timeout of every activity that heartbeats.
const heartbeatEvery = 30 * time.Second

// heartbeating heartbeats at half the timeout until the returned stop is called (auto_heartbeater).
func heartbeating(ctx context.Context) func() {
	done := make(chan struct{})
	go func() {
		t := time.NewTicker(heartbeatEvery / 2)
		defer t.Stop()
		for {
			select {
			case <-done:
				return
			case <-ctx.Done():
				return
			case <-t.C:
				activity.RecordHeartbeat(ctx)
			}
		}
	}()
	return func() { close(done) }
}

func principal(p Principal) service.Principal { return service.Principal(p) }

func toolCalls(in []ToolCall) []domain.ToolCall {
	if in == nil {
		return nil
	}
	out := make([]domain.ToolCall, len(in))
	for i, c := range in {
		out[i] = domain.ToolCall(c)
	}
	return out
}

func fromToolCalls(in []domain.ToolCall) []ToolCall {
	if in == nil {
		return nil
	}
	out := make([]ToolCall, len(in))
	for i, c := range in {
		out[i] = ToolCall(c)
	}
	return out
}

func imageRefs(in []ImageRef) []domain.ImageRef {
	if in == nil {
		return nil
	}
	out := make([]domain.ImageRef, len(in))
	for i, r := range in {
		out[i] = domain.ImageRef(r)
	}
	return out
}

func fromImageRefs(in []domain.ImageRef) []ImageRef {
	if in == nil {
		return nil
	}
	out := make([]ImageRef, len(in))
	for i, r := range in {
		out[i] = ImageRef(r)
	}
	return out
}

// pending is the request's messages not yet in the log.
func pending(msgs []Message) []domain.Entry {
	out := make([]domain.Entry, 0, len(msgs))
	for _, m := range msgs {
		kind := m.Kind
		if kind == "" {
			kind = domain.KindMessage
		}
		out = append(out, domain.Entry{
			Kind: kind, Role: m.Role, Content: m.Content, ToolCalls: toolCalls(m.ToolCalls),
			ToolCallID: m.ToolCallID, Name: m.Name, Attachments: imageRefs(m.Attachments), Meta: m.Meta,
		})
	}
	return out
}

func contextResult(content string, err error) ContextResult {
	if err != nil {
		return ContextResult{Error: err.Error()}
	}
	return ContextResult{Success: true, Content: content}
}

// StoreContextOutput is store_context_output; a failure is reported, not raised.
func (a *Activities) StoreContextOutput(ctx context.Context, req StoreOutputRequest) (ContextResult, error) {
	return contextResult("", a.svc.StoreOutput(ctx, principal(req.Principal), req.TaskID, req.OutputID, req.Content)), nil
}

// ReadContextOutput is read_context_output.
func (a *Activities) ReadContextOutput(ctx context.Context, req ReadOutputRequest) (ContextResult, error) {
	content, err := a.svc.ReadOutput(ctx, principal(req.Principal), req.TaskID, req.FilesTaskID, req.OutputID, req.Grep, req.Head, req.Tail)
	return contextResult(content, err), nil
}

// SearchHistory is search_history.
func (a *Activities) SearchHistory(ctx context.Context, req SearchHistoryRequest) (ContextResult, error) {
	content, err := a.svc.SearchHistory(ctx, principal(req.Principal), req.TaskID, req.Grep, req.ToolName)
	return contextResult(content, err), nil
}

// RecallHistory is recall_history_activity.
func (a *Activities) RecallHistory(ctx context.Context, req RecallHistoryRequest) (RecallHistoryResult, error) {
	r, err := a.svc.RecallHistory(ctx, principal(req.Principal), req.TaskID, req.EventTypes, req.Limit)
	if err != nil {
		return RecallHistoryResult{}, err
	}
	out := RecallHistoryResult{TotalCount: r.Total, Summary: r.Summary, Events: make([]FeedEvent, 0, len(r.Events))}
	for _, e := range r.Events {
		out.Events = append(out.Events, FeedEvent(e))
	}
	return out, nil
}

// DelegatedTaskSpend is delegated_task_spend_activity.
func (a *Activities) DelegatedTaskSpend(ctx context.Context, req DelegatedSpendRequest) (DelegatedSpendResult, error) {
	spent, err := a.svc.DelegatedSpend(ctx, principal(req.Principal), req.TaskID)
	return DelegatedSpendResult{Spent: spent}, err
}

// CheckMonthlySpendCap is check_monthly_spend_cap_activity.
func (a *Activities) CheckMonthlySpendCap(ctx context.Context, req MonthlySpendCapRequest) (MonthlySpendCapResult, error) {
	out, err := a.svc.CheckMonthlySpendCap(ctx, principal(req.Principal), service.SpendCapInput{
		WorkspaceCap: req.WorkspaceCap, AgentCap: req.AgentCap, LLMCaps: req.LLMCaps, CurrentCaps: req.CurrentCaps,
	})
	if err != nil {
		return MonthlySpendCapResult{}, err
	}
	return MonthlySpendCapResult(out), nil
}

// DeliverToRunner is deliver_to_runner_activity.
func (a *Activities) DeliverToRunner(ctx context.Context, req DeliverToRunnerRequest) error {
	return a.svc.DeliverToRunner(ctx, service.RunnerDelivery(req))
}

// ValidateArtifacts is validate_artifacts_activity.
func (a *Activities) ValidateArtifacts(ctx context.Context, req ArtifactValidationRequest) (ArtifactValidationResult, error) {
	v, err := a.svc.ValidateArtifacts(ctx, principal(req.Principal), req.TaskID, req.DeclaredPaths)
	if err != nil {
		return ArtifactValidationResult{}, err
	}
	out := ArtifactValidationResult{State: v.State, Generation: v.Generation}
	for _, e := range v.Evidence {
		out.Evidence = append(out.Evidence, ArtifactEvidence(e))
	}
	for _, i := range v.Issues {
		out.Issues = append(out.Issues, ArtifactIssue(i))
	}
	if v.Capability != "" {
		out.CapabilityUnavailable = &CapabilityUnavailable{Capability: v.Capability}
	}
	return out, nil
}

// ResolveRunConfig is resolve_run_config_activity.
func (a *Activities) ResolveRunConfig(ctx context.Context, req ResolveRunConfigRequest) (api.RunConfig, error) {
	s := req.Selections
	return a.svc.ResolveRunConfig(ctx, principal(req.Principal), service.ResolveInput{
		TaskID: req.TaskID, MCPInstanceIDs: s.MCPInstanceIDs, SkillIDs: s.SkillIDs, FileIDs: s.FileIDs,
		ModelOverride: s.ModelOverride, ProjectID: s.ProjectID, TriggerEvent: s.TriggerEvent,
		TriggerEventFileName: s.TriggerEventFileName, Policy: req.Policy, Governance: req.Governance,
	})
}

// UpdateGovernanceSnapshot is update_task_governance_snapshot_activity.
func (a *Activities) UpdateGovernanceSnapshot(ctx context.Context, req UpdateGovernanceSnapshotRequest) error {
	return a.svc.UpdateGovernanceSnapshot(ctx, principal(req.Principal), req.TaskID, req.Snapshot)
}

func statusUpdate(s *TaskStatus) *domain.StatusUpdate {
	if s == nil {
		return nil
	}
	cost := func(d *money.Decimal) *string {
		if d == nil {
			return nil
		}
		v := d.String()
		return &v
	}
	u := &domain.StatusUpdate{
		Status: s.Status, Response: s.Response, Artifacts: s.Artifacts, ValidationState: s.ValidationState,
		ErrorMessage: s.ErrorMessage, FailureReason: s.FailureReason, TotalCost: cost(s.TotalCost),
		OwnCost: cost(s.OwnCost), TokensUsed: s.TokensUsed, RunStartedAt: s.RunStartedAt,
	}
	if s.Resume != nil {
		r := domain.ResumePoint(*s.Resume)
		u.Resume = &r
	}
	return u
}

// Record is record_activity.
func (a *Activities) Record(ctx context.Context, req RecordRequest) (RecordResult, error) {
	in := service.RecordInput{TaskID: req.TaskID, ExecutionID: req.ExecutionID, Status: statusUpdate(req.Status)}
	for _, r := range req.Rows {
		in.Rows = append(in.Rows, domain.Entry{
			Seq: r.Seq, EventID: r.EventID, Kind: r.Kind, Role: r.Role, Content: r.Content, ToolCalls: toolCalls(r.ToolCalls),
			ToolCallID: r.ToolCallID, Name: r.Name, Attachments: imageRefs(r.Attachments), Meta: r.Meta,
			Iteration: r.Iteration, ExecutionID: req.ExecutionID, OccurredAt: r.Timestamp,
		})
	}
	for _, e := range req.Live {
		in.Live = append(in.Live, domain.StoredEvent{ID: e.ID, Type: e.Type, Timestamp: e.Timestamp, Data: e.Data})
	}
	out, err := a.svc.Record(ctx, principal(req.Principal), in)
	return RecordResult{Rows: out.Rows, Events: out.Events, TurnStart: req.TurnStart}, err
}

// ActivateSkill is activate_skill_activity.
func (a *Activities) ActivateSkill(ctx context.Context, req ActivateSkillRequest) (ActivateSkillResult, error) {
	defer heartbeating(ctx)()
	out, err := a.svc.ActivateSkill(ctx, principal(req.Principal), service.SkillActivation{
		TaskID: req.TaskID, FilesTaskID: req.FilesTaskID, ExecutionID: req.ExecutionID, ToolCallID: req.ToolCallID, Skill: req.Skill,
		WorkflowID: activity.GetInfo(ctx).WorkflowExecution.ID, Seq: req.Seq, EventID: req.EventID, Iteration: req.Iteration, MaxTokens: req.MaxTokens,
	})
	return ActivateSkillResult(out), err
}

// CreateDelegationTask is create_delegation_task_activity.
func (a *Activities) CreateDelegationTask(ctx context.Context, req CreateDelegationTaskRequest) (CreateDelegationTaskResult, error) {
	out, err := a.svc.CreateDelegationTask(ctx, principal(req.Principal), service.DelegationInput{
		ParentTaskID: req.ParentTaskID, TargetAgentID: req.TargetAgentID, TargetAgentName: req.TargetAgentName,
		Message: req.Message, ParentPolicy: req.ParentPolicy, RunBudget: req.RunBudget, ExecutionID: req.ExecutionID,
		WorkspaceTaskID: req.WorkspaceTaskID,
	})
	return CreateDelegationTaskResult(out), err
}

// RunRunnerTurn is run_runner_turn_activity: each update the runner sends is signalled to the run.
func (a *Activities) RunRunnerTurn(ctx context.Context, req RunnerTurnRequest) (RunnerTurnResult, error) {
	defer heartbeating(ctx)()
	if a.exec == nil {
		return RunnerTurnResult{}, errors.New("a runner turn needs the durable executor to signal its run")
	}
	turn := service.RunnerTurn{
		TaskID: req.TaskID, AgentID: req.AgentID, WorkspaceID: req.WorkspaceID, Iteration: req.Iteration,
		TurnKey: req.TurnKey, Message: req.Message,
	}
	if req.Actor != nil {
		turn.ActorType, turn.ActorID = req.Actor.Type, req.Actor.ID
	}
	workflowID := activity.GetInfo(ctx).WorkflowExecution.ID
	out, err := a.svc.RunRunnerTurn(ctx, turn, func(frame []byte) error {
		var update RunnerTurnUpdate
		if err := json.Unmarshal(frame, &update); err != nil {
			return err
		}
		activity.RecordHeartbeat(ctx)
		return a.exec.Signal(ctx, workflowID, api.SignalRunnerTurnUpdate, update)
	})
	return RunnerTurnResult(out), err
}

func usageOf(u modelsapi.Usage, billing *service.ChargeLine) LLMUsage {
	out := LLMUsage{
		PromptTokens: u.Prompt, CompletionTokens: u.Completion, TotalTokens: u.Total,
		CachedPromptTokens: u.CachedPrompt, CacheCreationTokens: u.CacheCreation,
	}
	if billing != nil {
		c := ChargeLine(*billing)
		out.Billing = &c
	}
	return out
}

// stoppedByRequest: the activity is cancelled because its run asked it to stop, not because the worker shuts down.
func stoppedByRequest(ctx context.Context) bool {
	if ctx.Err() == nil {
		return false
	}
	select {
	case <-activity.GetWorkerStopChannel(ctx):
		return false
	default:
		return true
	}
}

// CallLLM is call_llm_activity.
func (a *Activities) CallLLM(ctx context.Context, req LLMCallRequest) (LLMCallResult, error) {
	defer heartbeating(ctx)()
	in := service.LLMCall{
		TaskID: req.TaskID, ExecutionID: req.ExecutionID, Iteration: req.Iteration, Purpose: req.Purpose,
		Model: req.Model, Pending: pending(req.Messages), Tools: req.Tools, Temperature: req.Temperature,
		MaxTokens: req.MaxTokens, ReasoningEffort: req.ReasoningEffort, ReasoningMaxTokens: req.ReasoningMaxTokens,
		StreamText: req.StreamText, Policy: req.Policy, Stopped: func() bool { return stoppedByRequest(ctx) },
	}
	if req.Conversation != nil {
		next := req.Conversation.NextSeq
		in.NextSeq = &next
		if in.TaskID == "" {
			in.TaskID = req.Conversation.TaskID
		}
	}
	out, err := a.svc.CallLLM(ctx, principal(req.Principal), in)
	if err != nil {
		return LLMCallResult{}, err
	}
	billing := out.Billing
	return LLMCallResult{
		Role: "assistant", Content: out.Content, Thinking: out.Thinking, ToolCalls: fromToolCalls(out.ToolCalls),
		Cost: out.Cost, ProviderCostUSD: out.ProviderCostUSD, Currency: out.Currency, ManagedBy: out.ManagedBy,
		Usage: usageOf(out.Usage, &billing), Interrupted: out.Interrupted, FinishReason: out.FinishReason,
	}, nil
}

// CompactMessages is compact_messages_activity; the run appends the compaction row.
func (a *Activities) CompactMessages(ctx context.Context, req CompactMessagesRequest) (CompactMessagesResult, error) {
	defer heartbeating(ctx)()
	out, err := a.svc.CompactMessages(ctx, principal(req.Principal), service.Compaction{
		TaskID: req.Conversation.TaskID, NextSeq: req.Conversation.NextSeq, Pending: pending(req.Pending),
		HistoryChunkIndex: req.HistoryChunkIndex, Model: req.Model, Policy: req.Policy,
	})
	if err != nil {
		return CompactMessagesResult{}, err
	}
	return CompactMessagesResult{
		Summary: out.Summary, Skills: out.Skills, OriginalMessageCount: out.OriginalMessageCount,
		EstimatedTokensSaved: out.EstimatedTokensSaved, ContextTokens: out.ContextTokens,
		HistoryChunkStored: out.HistoryChunkStored, Cost: out.Cost, Usage: usageOf(out.Usage, out.Billing),
	}, nil
}

// ExecuteTool is execute_mcp_tool_activity.
func (a *Activities) ExecuteTool(ctx context.Context, req ToolCallRequest) (ToolCallResult, error) {
	defer heartbeating(ctx)()
	info := activity.GetInfo(ctx)
	started := time.Now()
	res, err := a.svc.ExecuteTool(ctx, principal(req.Principal), service.ToolCall{
		TaskID: req.TaskID, ExecutionID: req.ExecutionID, ToolCallID: req.ToolCallID, ToolName: req.ToolName,
		Args: req.Args, Binding: req.Binding, Policy: req.Policy, RunMetadata: req.RunMetadata,
		PolicyApprovalGranted: req.PolicyApprovalGranted || req.EscalationApproved,
		WorkflowID:            info.WorkflowExecution.ID, RunID: info.WorkflowExecution.RunID, ActivityID: info.ActivityID,
		Attempt: int(info.Attempt), Heartbeat: func() { activity.RecordHeartbeat(ctx) },
	})
	if err != nil {
		return ToolCallResult{}, err
	}
	o := res.Out
	out := ToolCallResult{
		Success: o.Success, Result: o.Result, Duration: time.Since(started), Error: o.Error, ExitCode: o.ExitCode,
		Outcome: o.Outcome, ArtifactPaths: o.ArtifactPaths, ServiceCost: o.ServiceCost, ModelCost: o.ModelCost,
		CostUnknown: o.CostUnknown, Cost: res.Cost, Payer: res.Payer, CostMetered: res.CostMetered, Replayed: res.Replayed,
		Attempt: res.Attempt, Source: o.Source, ServerInstanceID: o.ServerInstanceID, ServerName: o.ServerName,
		ServerIcon: o.ServerIcon, StructuredContent: o.StructuredContent, StructuredContentDropped: o.StructuredContentDropped,
		MCPAppTool: o.MCPAppTool, Images: fromImageRefs(res.Images), RemoteTask: o.RemoteTask,
	}
	if o.ModelBilling != nil {
		c := ChargeLine(*o.ModelBilling)
		out.ModelBilling = &c
	}
	for _, p := range o.Payments {
		out.Payments = append(out.Payments, Payment{
			Protocol: p.Protocol, Amount: p.Amount, Currency: p.Currency, Network: p.Network, Reference: p.Reference, Settled: p.Settled,
		})
	}
	return out, nil
}

func remoteTaskCall(ctx context.Context, req RemoteTaskRequest) service.ToolCall {
	info := activity.GetInfo(ctx)
	return service.ToolCall{
		TaskID: req.TaskID, ExecutionID: req.ExecutionID, ToolCallID: req.ToolCallID, ToolName: req.ToolName, Binding: req.Binding,
		WorkflowID: info.WorkflowExecution.ID, RunID: info.WorkflowExecution.RunID, ActivityID: info.ActivityID, Attempt: int(info.Attempt),
	}
}

// GetRemoteTask reads the task a remote delegate call started, once.
func (a *Activities) GetRemoteTask(ctx context.Context, req RemoteTaskRequest) (ToolCallResult, error) {
	res, err := a.svc.GetRemoteTask(ctx, principal(req.Principal), remoteTaskCall(ctx, req), req.Task)
	if err != nil {
		return ToolCallResult{}, err
	}
	o := res.Out
	return ToolCallResult{
		Success: o.Success, Result: o.Result, Error: o.Error, Source: o.Source, Images: fromImageRefs(res.Images), RemoteTask: o.RemoteTask,
	}, nil
}

// CancelRemoteTask asks the remote delegate to stop the task a call started.
func (a *Activities) CancelRemoteTask(ctx context.Context, req RemoteTaskRequest) error {
	return a.svc.CancelRemoteTask(ctx, principal(req.Principal), remoteTaskCall(ctx, req), req.Task)
}
