package workflows

import (
	"slices"
	"time"

	"go.temporal.io/sdk/workflow"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/domain"
)

// agentRun is the state of one AgentExecutionWorkflow execution. The workflow
// history is the loop state; the conversation lives in the task log.
type agentRun struct {
	ids   *ids
	queue string

	executionID string
	principal   Principal
	taskID      string
	goal        *Goal
	cfg         api.RunConfig
	configured  bool
	tools       []api.ToolDefinition
	metadata    map[string]any
	interaction domain.InteractionCapabilities

	status             string
	iteration          int
	toolCallsUsed      int
	tokensUsed         int64
	lastPromptTokens   int64
	messages           []Message
	nextSeq            int64
	seenURLs           []string
	truncatedReply     string
	success            bool
	finalResponse      string
	failureReason      string
	errorMessage       string
	blockedReason      string
	validationState    string
	validationRepairs  int
	validationTerminal bool

	budgetLimit       money.Decimal
	cost              money.Decimal
	currency          string
	budgetWarningSent bool
	delegatedCost     money.Decimal
	serviceCostUsed   money.Decimal
	llmCostUsed       money.Decimal

	contextWindow      int
	contextUsage       int64
	contextWarningSent bool
	compactionCount    int
	historyChunks      int
	activatedSkills    []string
	skillTokensUsed    int
	activatedSources   []string
	revealedTools      []string
	runStartedAt       *time.Time
	chainExpiresAt     *time.Time
	continuedFromRunID string

	paused               bool
	pauseReason          string
	awaitingInput        bool
	escalations          map[string]*Escalation
	escalationOrder      []string
	inputRequests        map[string]*InputRequest
	inputOrder           []string
	messageQueue         []QueuedMessage
	a2uiQueue            []map[string]any
	a2uiSurfaces         map[string]map[string]string
	completionPublished  bool
	waitingContinuation  bool
	continuationInFlight bool
	continuationReason   string
	continuationMessage  string
	continuationCount    int
	policyFixedLimit     string
	monthlyCapMessage    string
	reportedLLMFailure   error
	completedStatus      *TaskStatus

	agentSpendBaseline   *money.Decimal
	agentSpendMark       money.Decimal
	agentCapCountsSvc    bool
	agentCapCurrency     string
	agentCapReadCurrent  bool
	currentAgentCap      *money.Decimal
	resumePromptMissing  bool
	conversationSeeded   bool
	turnCallIDs          []string
	recordedTurnCalls    []ToolCall
	recordedTurnAnswered []string
	stoppedToolCalls     []ToolCall
	stoppedModelCall     bool
	compactionFloor      *int64
	awaitingFloor        bool

	waitingForOutage  bool
	outageReason      string
	outageServiceName string
	outageSince       time.Time
	retryOutageNow    bool
	wakeWait          bool

	runner runnerState

	pending []Event
}

func newAgentRun() *agentRun {
	return &agentRun{
		status:          StatusInitializing,
		validationState: "pending",
		escalations:     map[string]*Escalation{},
		inputRequests:   map[string]*InputRequest{},
		a2uiSurfaces:    map[string]map[string]string{},
		interaction:     domain.DefaultInteraction(),
		metadata:        map[string]any{},
	}
}

// emit adds an event to the pending events (EventManager.add_event): payload
// first, the run's identity last, sanitized where the type needs it.
func (r *agentRun) emit(ctx workflow.Context, eventType string, data map[string]any) {
	if !domain.KnownEventType(eventType) {
		panic("runs: unknown event type " + eventType)
	}
	switch eventType {
	case domain.EventLLMCompleted:
		data = sanitizeLLMCompleted(data)
	case domain.EventToolResult:
		data = domain.SanitizeToolResultData(data)
	}
	out := make(map[string]any, len(data)+4)
	for k, v := range data {
		out[k] = v
	}
	out["task_id"] = r.taskID
	out["agent_id"] = r.principal.AgentID
	out["execution_id"] = r.executionID
	if r.principal.WorkspaceID != "" {
		out["workspace_id"] = r.principal.WorkspaceID
	}
	out = domain.EnsureTerminalMessage(eventType, out)
	r.pending = append(r.pending, Event{ID: r.ids.uuid(), Type: eventType, Data: out, Timestamp: workflow.Now(ctx).UTC()})
}

func sanitizeLLMCompleted(data map[string]any) map[string]any {
	out := make(map[string]any, len(data))
	for k, v := range data {
		out[k] = v
	}
	content, _ := data["content"].(string)
	out["content"] = domain.BoundedLLMContent(content)
	out["tool_calls"] = domain.SanitizeToolEventValue(data["tool_calls"], "")
	if t, ok := out["thinking"]; ok {
		out["thinking"] = domain.SanitizeToolEventValue(t, "thinking")
	}
	return out
}

// record writes the pending rows, the task status and the events in one
// record activity; every row carries an id the workflow assigned.
func (r *agentRun) record(ctx workflow.Context, status *TaskStatus) error {
	events := r.pending
	messages := r.messages
	if len(events) == 0 && len(messages) == 0 && status == nil {
		return nil
	}
	r.pending = nil
	iteration := r.iteration
	rows := make([]LogRow, 0, len(messages)+len(events))
	for i, m := range messages {
		rows = append(rows, LogRow{
			Seq: r.nextSeq + int64(i), EventID: r.ids.uuid(), Kind: kindOf(m), Role: m.Role, Content: m.Content,
			ToolCalls: m.ToolCalls, ToolCallID: m.ToolCallID, Name: m.Name, Attachments: m.Attachments,
			Meta: m.Meta, Iteration: ptr(iteration),
		})
	}
	var live []Event
	for _, e := range events {
		if domain.LiveOnly(e.Type) {
			live = append(live, e)
			continue
		}
		ts := e.Timestamp
		rows = append(rows, LogRow{
			Seq: r.nextSeq + int64(len(rows)), EventID: e.ID, Kind: "event", Role: "event", Name: e.Type,
			Meta: e.Data, Iteration: ptr(iteration), Timestamp: &ts,
		})
	}
	req := RecordRequest{Principal: r.principal, TaskID: r.taskID, ExecutionID: r.executionID, Rows: rows, Live: live, Status: status}
	var res RecordResult
	if err := workflow.ExecuteActivity(activityCtx(ctx, api.ActivityRecord, "", 0), api.ActivityRecord, req).Get(ctx, &res); err != nil {
		return err
	}
	r.rememberExternalURLs(messages)
	r.messages = slices.Clone(r.messages[len(messages):])
	r.nextSeq += int64(len(rows))
	for _, m := range messages {
		switch {
		case m.Role == "assistant":
			r.recordedTurnCalls = slices.Clone(m.ToolCalls)
			r.recordedTurnAnswered = nil
		case m.Role == "tool" && m.ToolCallID != "":
			r.recordedTurnAnswered = append(r.recordedTurnAnswered, m.ToolCallID)
		}
	}
	return nil
}

func kindOf(m Message) string {
	if m.Kind == "" {
		return "message"
	}
	return m.Kind
}

func (r *agentRun) publish(ctx workflow.Context) error { return r.record(ctx, nil) }

func (r *agentRun) persistStatus(ctx workflow.Context, st TaskStatus) error {
	st.RunStartedAt = r.runStartedAt
	return r.record(ctx, &st)
}

func (r *agentRun) statusOnly(status string) TaskStatus { return TaskStatus{Status: status} }

func (r *agentRun) rememberExternalURLs(messages []Message) {
	var entries []domain.Entry
	for _, m := range messages {
		entries = append(entries, domain.Entry{Role: m.Role, Content: m.Content})
	}
	for _, u := range domain.ExternalURLs(entries) {
		if !slices.Contains(r.seenURLs, u) {
			r.seenURLs = append(r.seenURLs, u)
		}
	}
	if len(r.seenURLs) > seenURLsLimit {
		r.seenURLs = r.seenURLs[len(r.seenURLs)-seenURLsLimit:]
	}
}

func (r *agentRun) counters() Counters {
	return Counters{Cost: r.cost, Tokens: r.tokensUsed, ServiceCost: r.serviceCostUsed}
}

func (r *agentRun) ownCost() money.Decimal {
	return maxDec(r.cost.Sub(r.delegatedCost), money.Zero())
}

func (r *agentRun) remaining() money.Decimal {
	return maxDec(r.budgetLimit.Sub(r.cost), money.Zero())
}

func (r *agentRun) describe(d money.Decimal) string {
	if r.currency != "" {
		return d.String() + " " + r.currency
	}
	return d.String()
}

func (r *agentRun) isDelegationChild() bool { return r.metadata["source"] == "agent_delegation" }

func (r *agentRun) questionsAvailable() bool {
	return domain.QuestionsAvailable(r.cfg.Policy, r.interaction.AllowQuestions)
}

func (r *agentRun) a2uiAvailable() bool { return r.cfg.Agent.A2UIEnabled && r.interaction.AllowA2UI }

func (r *agentRun) followUpWindow() (time.Duration, bool) {
	var params map[string]any
	if r.goal != nil {
		params = r.goal.Context
	}
	return domain.FollowUpWindow(params, r.interaction)
}

func (r *agentRun) callInHistory(id string) bool {
	if slices.Contains(r.turnCallIDs, id) {
		return true
	}
	for _, m := range r.messages {
		for _, c := range m.ToolCalls {
			if c.ID == id {
				return true
			}
		}
	}
	return false
}

// lastTurnToolCalls are the latest model turn's calls and the ids a result answers.
func (r *agentRun) lastTurnToolCalls() ([]ToolCall, []string) {
	last := -1
	for i := len(r.messages) - 1; i >= 0; i-- {
		if r.messages[i].Role == "assistant" {
			last = i
			break
		}
	}
	var calls []ToolCall
	var answered []string
	after := r.messages
	if last >= 0 {
		calls = slices.Clone(r.messages[last].ToolCalls)
		after = r.messages[last+1:]
	} else {
		calls = slices.Clone(r.recordedTurnCalls)
		answered = slices.Clone(r.recordedTurnAnswered)
	}
	for _, m := range after {
		if m.Role == "tool" && m.ToolCallID != "" {
			answered = append(answered, m.ToolCallID)
		}
	}
	return calls, answered
}

func (r *agentRun) answerUnansweredToolCalls(content string) {
	calls, answered := r.lastTurnToolCalls()
	for _, c := range calls {
		if c.ID != "" && !slices.Contains(answered, c.ID) {
			r.messages = append(r.messages, Message{Role: "tool", Content: content, ToolCallID: c.ID, Name: c.Name})
			answered = append(answered, c.ID)
		}
	}
}

func (r *agentRun) answerStoppedToolCalls() {
	calls, _ := r.lastTurnToolCalls()
	for _, c := range calls {
		if slices.ContainsFunc(r.stoppedToolCalls, func(s ToolCall) bool { return s.ID == c.ID }) {
			r.messages = append(r.messages, Message{Role: "tool", Content: stoppedWhileRunning, ToolCallID: c.ID, Name: c.Name})
		}
	}
	r.answerUnansweredToolCalls(stoppedBeforeRunning)
}

func (r *agentRun) keepQueuedMessages() {
	if len(r.messageQueue) == 0 {
		return
	}
	if !r.conversationSeeded && r.goal != nil {
		r.messages = append(r.messages, Message{Role: "user", Content: r.goal.Description})
	}
	for _, q := range r.messageQueue {
		r.messages = append(r.messages, Message{Role: "user", Content: q.Content})
	}
	r.messageQueue = nil
}

func (r *agentRun) resumable() bool { return r.conversationSeeded && !r.resumePromptMissing }

func (r *agentRun) resumeSnapshot(pending int) *ResumeSnapshot {
	return &ResumeSnapshot{
		NextSeq: r.nextSeq + int64(pending), CurrentIteration: max(r.iteration, 1),
		ToolCallsUsed: r.toolCallsUsed, TokensUsed: r.tokensUsed, LastPromptTokens: r.lastPromptTokens,
	}
}

// toolCallsValue is a turn's tool calls as the Python events carry them.
func toolCallsValue(calls []ToolCall) []any {
	out := make([]any, 0, len(calls))
	for _, c := range calls {
		out = append(out, map[string]any{
			"id": c.ID, "type": "function",
			"function": map[string]any{"name": c.Name, "arguments": c.Arguments},
		})
	}
	return out
}

func (r *agentRun) offered(name string) bool {
	for _, t := range r.tools {
		if t.Name == name {
			return true
		}
	}
	return false
}
