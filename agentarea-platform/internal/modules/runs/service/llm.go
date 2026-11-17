package service

import (
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"slices"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/analytics"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

// LLMCall is one model call of a run (llm.py call_llm_activity). With
// NextSeq the window is read from the task log before it, then Pending.
type LLMCall struct {
	TaskID, ExecutionID string
	Iteration           int
	Purpose             string
	Model               api.ResolvedModel
	NextSeq             *int64
	Pending             []domain.Entry
	Tools               []api.ToolDefinition
	Temperature         *float64
	MaxTokens           *int
	ReasoningEffort     string
	ReasoningMaxTokens  *int
	StreamText          bool
	Policy              api.Policy
	// Stopped reports whether the run asked the call to stop (not a worker shutdown).
	Stopped func() bool
}

// LLMResult is the reply and what it cost, as billing says it.
type LLMResult struct {
	Content, Thinking string
	ToolCalls         []domain.ToolCall
	Cost              money.Decimal
	ProviderCostUSD   money.Decimal
	Currency          string
	ManagedBy         string
	Usage             modelsapi.Usage
	Billing           ChargeLine
	Interrupted       bool
	FinishReason      string
}

// ErrStoppedWithoutUsage: a reply cut short before the provider reported usage stays a cancellation.
var ErrStoppedWithoutUsage = errors.New("the model call was stopped before the provider reported usage")

func modelCallFailure(prefix string, err error) error {
	var app *durable.ApplicationError
	if errors.As(err, &app) {
		if app.Type == "SpendCapReachedError" || app.Type == "GovernanceDeniedError" || app.Type == "ReasoningSettingError" ||
			app.Type == "ModelChargeUnavailableError" || strings.HasPrefix(app.Message, prefix) {
			return err
		}
		return &durable.ApplicationError{Type: app.Type, Message: prefix + app.Message, NonRetryable: app.NonRetryable, Details: app.Details, Cause: app.Cause}
	}
	if errors.Is(err, ErrStoppedWithoutUsage) || errors.Is(err, context.Canceled) {
		return err
	}
	return &durable.ApplicationError{Type: "RuntimeError", Message: prefix + err.Error(), Cause: err}
}

// maxTokensFor is the strictest output ceiling: the policy's per-call cap, the request's, the model's.
func maxTokensFor(requested, modelCap *int, policy api.Policy) (int, error) {
	if policy.Tokens == nil || policy.Tokens.MaxTokensPerCall == nil || *policy.Tokens.MaxTokensPerCall <= 0 {
		return 0, nonRetryable("ValueError", "effective policy is missing required runtime limit tokens.max_tokens_per_call", nil)
	}
	limit := *policy.Tokens.MaxTokensPerCall
	for name, v := range map[string]*int{"request.max_tokens": requested, "model.max_output_tokens": modelCap} {
		if v == nil {
			continue
		}
		if *v <= 0 {
			return 0, nonRetryable("ValueError", name+" must be a positive integer", nil)
		}
		limit = min(limit, *v)
	}
	return limit, nil
}

func checkEffort(effort string, model api.ResolvedModel) error {
	levels := model.ReasoningLevels
	if effort == "" || len(levels) == 0 || slices.Contains(levels, effort) {
		return nil
	}
	return nonRetryable("ReasoningSettingError", fmt.Sprintf("model %s takes reasoning_effort %s, not %s", model.ModelName, strings.Join(levels, ", "), effort), nil)
}

// window is read_window: the log's model window before nextSeq, then the pending messages.
func (s *Service) window(ctx context.Context, ws scope.Workspace, taskID string, nextSeq int64, pending []domain.Entry) ([]domain.Entry, error) {
	var logged []domain.Entry
	err := s.readSession(ctx, ws, func(tx db.Session) error {
		var err error
		logged, err = s.store.Window(ctx, tx, taskID, nextSeq)
		return err
	})
	if err != nil {
		return nil, err
	}
	if logged, err = s.resolveBodies(ctx, logged); err != nil {
		return nil, err
	}
	out := domain.ModelWindow(logged)
	for i, e := range pending {
		if e.Kind == domain.KindEvent {
			continue
		}
		e.Seq = nextSeq + int64(i)
		if e.Kind == "" {
			e.Kind = domain.KindMessage
		}
		out = append(out, e)
	}
	return out, nil
}

func messagesOf(entries []domain.Entry) []domain.ChatMessage {
	out := make([]domain.ChatMessage, 0, len(entries))
	for _, e := range entries {
		out = append(out, e.AsMessage())
	}
	return out
}

// withToolImages attaches the newest images tools returned, read from the task's context store.
func (s *Service) withToolImages(ctx context.Context, p Principal, taskID string, messages []domain.ChatMessage, vision bool) ([]domain.ModelMessage, error) {
	urls := map[string]*string{}
	has := slices.ContainsFunc(messages, func(m domain.ChatMessage) bool { return len(m.Attachments) > 0 })
	if has && taskID == "" {
		return nil, nonRetryable("ValueError", "tool images need the task they were stored under", nil)
	}
	if has && vision {
		mime := map[string]string{}
		for _, m := range messages {
			for _, ref := range m.Attachments {
				mime[ref.ID] = ref.MimeType
			}
		}
		for _, id := range domain.ImagesToAttach(messages, domain.MaxImagesPerModelCall) {
			body, err := s.getText(ctx, domain.ImageKey(p.WorkspaceID, taskID, id))
			if err != nil {
				s.d.Log.WarnContext(ctx, "tool image could not be read", "image_id", id, "error", err)
				urls[id] = nil
				continue
			}
			url := "data:" + mime[id] + ";base64," + base64.StdEncoding.EncodeToString([]byte(body))
			urls[id] = &url
		}
	}
	return domain.AttachToolImages(messages, urls, vision), nil
}

// CallLLM makes one model call of a run, funded, held and priced by billing,
// and streams its reply as llm.call.chunk snapshots.
func (s *Service) CallLLM(ctx context.Context, p Principal, in LLMCall) (LLMResult, error) {
	out, err := s.callLLM(ctx, p, in)
	if err != nil {
		s.d.Log.ErrorContext(ctx, "LLM call failed", "task_id", in.TaskID, "error", err)
		return LLMResult{}, modelCallFailure("LLM call failed: ", err)
	}
	return out, nil
}

func (s *Service) callLLM(ctx context.Context, p Principal, in LLMCall) (LLMResult, error) {
	ws, err := workspace(p)
	if err != nil {
		return LLMResult{}, err
	}
	if s.d.Models == nil {
		return LLMResult{}, errors.New("a model call needs the model caller")
	}
	if err := s.gateModelCall(ctx, p, in.Model, in.Policy); err != nil {
		return LLMResult{}, err
	}
	entries := in.Pending
	if in.NextSeq != nil {
		if entries, err = s.window(ctx, ws, in.TaskID, *in.NextSeq, in.Pending); err != nil {
			return LLMResult{}, err
		}
	}
	if err := checkEffort(in.ReasoningEffort, in.Model); err != nil {
		return LLMResult{}, err
	}
	messages, err := s.withToolImages(ctx, p, in.TaskID, messagesOf(entries), in.Model.SupportsVision)
	if err != nil {
		return LLMResult{}, err
	}
	maxTokens, err := maxTokensFor(in.MaxTokens, in.Model.MaxOutputTokens, in.Policy)
	if err != nil {
		return LLMResult{}, err
	}
	if err := s.refuseAtSpendCap(ctx, p, in.Policy.Budget); err != nil {
		return LLMResult{}, err
	}
	f, err := s.holdModelCall(ctx, p, in.Model, estimateVendorCost(messages, maxTokens, in.Model.Prices), "llm:"+in.TaskID+":"+strings.ReplaceAll(newID(), "-", ""))
	if err != nil {
		return LLMResult{}, err
	}
	var onChunk func(modelsapi.Chunk)
	if in.TaskID != "" && s.d.Events != nil {
		onChunk = s.chunkPublisher(ctx, in.TaskID, in.ExecutionID, in.Iteration, in.StreamText)
	}
	reply, err := s.d.Models.Call(ctx, modelsapi.Principal(p), modelsapi.Call{
		Model: in.Model, Messages: modelMessages(messages), Tools: modelTools(in.Tools), Temperature: in.Temperature, MaxTokens: maxTokens,
		ReasoningEffort: in.ReasoningEffort, ReasoningMaxTokens: in.ReasoningMaxTokens, Funded: f.platformFunded, OnChunk: onChunk,
	})
	if err == nil && reply.Usage.Total <= 0 {
		if reply.Interrupted {
			err = ErrStoppedWithoutUsage
		} else {
			err = errors.New("LLM usage accounting unavailable; token and cost policy cannot be enforced")
		}
	}
	if err != nil {
		s.releaseHold(ctx, f, "the model call did not complete")
		return LLMResult{}, err
	}
	if reply.Interrupted && (in.Stopped == nil || !in.Stopped()) {
		s.releaseHold(ctx, f, "the model call was cancelled")
		return LLMResult{}, context.Canceled
	}
	charge, err := s.chargeModelCall(ctx, f, reply.ProviderCostUSD)
	if err != nil {
		return LLMResult{}, err
	}
	if onChunk != nil {
		onChunk(modelsapi.Chunk{Final: true, Index: reply.ChunkCount})
	}
	return LLMResult{
		Content: reply.Content, Thinking: reply.Thinking, ToolCalls: replyToolCalls(reply.ToolCalls), Cost: charge.Amount,
		ProviderCostUSD: reply.ProviderCostUSD, Currency: charge.Currency, ManagedBy: in.Model.ManagedBy,
		Usage: reply.Usage, Billing: charge, Interrupted: reply.Interrupted, FinishReason: reply.FinishReason,
	}, nil
}

// Compaction asks for a summary of a task's conversation (compact_messages_activity).
type Compaction struct {
	TaskID            string
	NextSeq           int64
	Pending           []domain.Entry
	HistoryChunkIndex *int
	Model             api.ResolvedModel
	Policy            api.Policy
}

// Compacted is the summary the run appends as a compaction row; OriginalMessageCount 0: nothing to compact.
type Compacted struct {
	Summary              string
	Skills               []string
	OriginalMessageCount int
	EstimatedTokensSaved int
	ContextTokens        int
	HistoryChunkStored   bool
	Cost                 money.Decimal
	Usage                modelsapi.Usage
	Billing              *ChargeLine
}

// CompactMessages summarizes the whole window, the previous compaction folded in; nothing is written but the history chunk.
func (s *Service) CompactMessages(ctx context.Context, p Principal, in Compaction) (Compacted, error) {
	out, err := s.compact(ctx, p, in)
	if err != nil {
		s.d.Log.ErrorContext(ctx, "message compaction failed", "task_id", in.TaskID, "error", err)
		return Compacted{}, modelCallFailure("Message compaction failed: ", err)
	}
	return out, nil
}

func (s *Service) compact(ctx context.Context, p Principal, in Compaction) (Compacted, error) {
	ws, err := workspace(p)
	if err != nil {
		return Compacted{}, err
	}
	if s.d.Models == nil {
		return Compacted{}, errors.New("a compaction needs the model caller")
	}
	entries, err := s.window(ctx, ws, in.TaskID, in.NextSeq, in.Pending)
	if err != nil {
		return Compacted{}, err
	}
	toCompact, skills, removed := domain.CompactionInput(entries)
	if len(removed) == 0 {
		return Compacted{ContextTokens: domain.MessagesTokens(messagesOf(entries))}, nil
	}
	var system []domain.Entry
	for _, e := range entries {
		if e.Kind == domain.KindMessage && e.Role == "system" {
			system = append(system, e)
			break
		}
	}
	stored := false
	if in.HistoryChunkIndex != nil {
		if err := s.StoreHistoryChunk(ctx, p, in.TaskID, *in.HistoryChunkIndex, messagesOf(removed)); err != nil {
			s.d.Log.WarnContext(ctx, "history chunk was not stored", "chunk", *in.HistoryChunkIndex, "task_id", in.TaskID, "error", err)
		} else {
			stored = true
		}
	}
	maxTokens, err := maxTokensFor(nil, in.Model.MaxOutputTokens, in.Policy)
	if err != nil {
		return Compacted{}, err
	}
	messages := []domain.ModelMessage{
		{Role: "system", Content: domain.CompactionSystemPrompt},
		{Role: "user", Content: domain.CompactionPrompt(toCompact)},
	}
	if err := s.refuseAtSpendCap(ctx, p, in.Policy.Budget); err != nil {
		return Compacted{}, err
	}
	f, err := s.holdModelCall(ctx, p, in.Model, estimateVendorCost(messages, maxTokens, in.Model.Prices), "llm:"+in.TaskID+":compaction:"+strings.ReplaceAll(newID(), "-", ""))
	if err != nil {
		return Compacted{}, err
	}
	reply, err := s.d.Models.Call(ctx, modelsapi.Principal(p), modelsapi.Call{Model: in.Model, Messages: modelMessages(messages), MaxTokens: maxTokens, Funded: f.platformFunded})
	if err == nil && reply.Usage.Total <= 0 {
		err = errors.New("compaction usage accounting unavailable; budget cannot be enforced")
	}
	if err != nil {
		s.releaseHold(ctx, f, "the compaction call did not complete")
		return Compacted{}, err
	}
	charge, err := s.chargeModelCall(ctx, f, reply.ProviderCostUSD)
	if err != nil {
		return Compacted{}, err
	}
	original := domain.MessagesTokens(messagesOf(removed))
	compaction := domain.Entry{Kind: domain.KindCompaction, Role: "user", Content: domain.CompactionSummaryHeader + "\n" + reply.Content}
	return Compacted{
		Summary: reply.Content, Skills: skills, OriginalMessageCount: len(removed),
		EstimatedTokensSaved: max(0, original-len([]rune(reply.Content))/4),
		ContextTokens:        domain.MessagesTokens(messagesOf(append(system, compaction))),
		HistoryChunkStored:   stored, Cost: charge.Amount, Usage: reply.Usage, Billing: &charge,
	}, nil
}

func replyToolCalls(in []modelsapi.ToolCall) []domain.ToolCall {
	if in == nil {
		return nil
	}
	out := make([]domain.ToolCall, len(in))
	for i, c := range in {
		out[i] = domain.ToolCall(c)
	}
	return out
}

// gateModelCall asks the entitlement gate before the call is funded; a deny
// or an escalation reaches the workflow as the gate's verdict, never retried.
func (s *Service) gateModelCall(ctx context.Context, p Principal, model api.ResolvedModel, policy api.Policy) error {
	if s.d.Entitlement == nil {
		return nil
	}
	if p.UserID == "" {
		return errors.New("governed model call has no principal; refusing to evaluate policy without one")
	}
	res, err := s.d.Entitlement.CheckLLMCall(ctx, LLMGateCall{
		WorkspaceID: p.WorkspaceID, UserID: p.UserID, AgentID: p.AgentID,
		ModelID: model.ModelID, ModelName: model.ModelName, ManagedBy: model.ManagedBy,
		ExecutionState: gateState(policy),
	})
	if err != nil {
		return err
	}
	errType := ""
	switch res.Action {
	case "deny":
		errType = "GovernanceDeniedError"
		code, ok := res.Metadata["entitlement_code"].(string)
		if !ok {
			analytics.RunRefused(s.d.Counter, nil)
		} else {
			analytics.RunRefused(s.d.Counter, &code)
		}
	case "escalate":
		errType = "EscalationRequiredError"
	default:
		return nil
	}
	return nonRetryable(errType, res.InterceptorName+": "+res.Reason, nil, map[string]any{
		"interceptor_name": res.InterceptorName, "reason": res.Reason, "metadata": orEmptyMap(res.Metadata), "phase": "pre_llm_call",
	})
}

// gateState is the budget and token part of to_execution_state.
func gateState(policy api.Policy) map[string]any {
	state := map[string]any{}
	if b := policy.Budget; b != nil {
		if b.RunBudget != nil {
			state["budget_usd"] = *b.RunBudget
		}
		if b.ServiceBudget != nil {
			state["service_budget_usd"] = *b.ServiceBudget
		}
	}
	if t := policy.Tokens; t != nil {
		if t.MaxTokens != nil {
			state["max_tokens"] = *t.MaxTokens
		}
		if t.MaxTokensPerCall != nil {
			state["max_tokens_per_call"] = *t.MaxTokensPerCall
		}
	}
	return state
}

func orEmptyMap(m map[string]any) map[string]any {
	if m == nil {
		return map[string]any{}
	}
	return m
}
