package domain

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

// A2AResponseArtifactName names the artifact that carries the agent's answer.
const A2AResponseArtifactName = "agent-response"

// A2AAgentKeyMetadata is the task metadata key holding the agent key a task was started with.
const A2AAgentKeyMetadata = "a2a_agent_key_id"

// A2A task states as the wire names them.
const (
	A2AStateUnspecified   = "TASK_STATE_UNSPECIFIED"
	A2AStateSubmitted     = "TASK_STATE_SUBMITTED"
	A2AStateWorking       = "TASK_STATE_WORKING"
	A2AStateCompleted     = "TASK_STATE_COMPLETED"
	A2AStateFailed        = "TASK_STATE_FAILED"
	A2AStateCanceled      = "TASK_STATE_CANCELED"
	A2AStateInputRequired = "TASK_STATE_INPUT_REQUIRED"
	A2AStateRejected      = "TASK_STATE_REJECTED"
)

func a2aTaskStates() map[string]string {
	return map[string]string{
		"submitted": A2AStateSubmitted, "pending": A2AStateSubmitted, "preparing": A2AStateSubmitted, "scheduled": A2AStateSubmitted,
		"running": A2AStateWorking, "working": A2AStateWorking,
		"waiting_for_input": A2AStateInputRequired, "waiting_for_approval": A2AStateInputRequired,
		"waiting_for_continuation": A2AStateInputRequired, "waiting_for_infrastructure": A2AStateWorking,
		"completed": A2AStateCompleted, "failed": A2AStateFailed, "blocked": A2AStateFailed,
		"cancelled": A2AStateCanceled, "canceled": A2AStateCanceled,
	}
}

// A2ATaskState is task_state; known is false for a status with no A2A state
// (Python logs it), which reads as unspecified.
func A2ATaskState(status string) (state string, known bool) {
	s, ok := a2aTaskStates()[status]
	if !ok {
		return A2AStateUnspecified, false
	}
	return s, true
}

// A2ATerminalState is TERMINAL_STATES.
func A2ATerminalState(state string) bool {
	switch state {
	case A2AStateCompleted, A2AStateFailed, A2AStateCanceled, A2AStateRejected:
		return true
	}
	return false
}

// Workflow event types the A2A stream reads (events/contract.py).
const (
	a2aLLMChunk                   = "llm.call.chunk"
	a2aToolCall                   = "tool.call"
	a2aToolResult                 = "tool.result"
	a2aToolProgress               = "tool.progress"
	a2aInputRequest               = "input.request"
	a2aApprovalRequested          = "approval.requested"
	a2aTaskCompleted              = "task.completed"
	a2aTaskFailed                 = "task.failed"
	a2aTaskCancelled              = "task.cancelled"
	a2aTaskAwaitingContinuation   = "task.awaiting_continuation"
	a2aTaskAwaitingInfrastructure = "task.awaiting_infrastructure"
	a2aTurnStarted                = "turn.started"
	a2aContextCompacted           = "context.compacted"
	a2aDelegationStarted          = "delegation.started"
	a2aDelegationCompleted        = "delegation.completed"
	a2aDelegationFailed           = "delegation.failed"
)

func a2aTerminalEvents() map[string]string {
	return map[string]string{
		a2aTaskCompleted: A2AStateCompleted, a2aTaskFailed: A2AStateFailed, a2aTaskCancelled: A2AStateCanceled,
	}
}

// A2ACanonicalType is canonical_type: the event type without the "workflow." prefix.
func A2ACanonicalType(eventType string) string { return strings.TrimPrefix(eventType, "workflow.") }

// A2ATerminalEvent is membership of TERMINAL_EVENT_TYPES.
func A2ATerminalEvent(canonical string) bool { _, ok := a2aTerminalEvents()[canonical]; return ok }

// A2ATaskRow is what an A2A Task is read from: a task row.
type A2ATaskRow struct {
	ID           string
	Status       string
	Result       any
	ErrorMessage *string
	Metadata     A2AJSON
	UpdatedAt    *time.Time
}

// A2AContextID is context_id_for: the contextId the client sent, else the task id.
func A2AContextID(t A2ATaskRow) string {
	if v, _ := t.Metadata.Get("a2a_context_id"); a2aTruthy(v) {
		return a2aPyStr(v)
	}
	return t.ID
}

// A2AFinalText is final_text: the agent's final answer in the task result.
func A2AFinalText(result any) (string, bool) {
	r, ok := result.(A2AJSON)
	if !ok {
		return "", false
	}
	for _, key := range []string{"response", "final_response", "result", "text"} {
		if s, ok := a2aString(r, key); ok && a2aPyStrip(s) != "" {
			return s, true
		}
	}
	return "", false
}

// A2ATimestamp is Timestamp.FromDatetime rendered by MessageToDict (RFC 3339, UTC).
func A2ATimestamp(t time.Time) string {
	t = t.UTC()
	out := t.Format("2006-01-02T15:04:05")
	switch n := t.Nanosecond(); {
	case n == 0:
	case n%1_000_000 == 0:
		out += fmt.Sprintf(".%03d", n/1_000_000)
	case n%1_000 == 0:
		out += fmt.Sprintf(".%06d", n/1_000)
	default:
		out += fmt.Sprintf(".%09d", n)
	}
	return out + "Z"
}

func a2aTextParts(text string) []any { return []any{A2AJSON{{Key: "text", Value: text}}} }

func a2aAgentMessage(id, text string) A2AJSON {
	return A2AJSON{{Key: "messageId", Value: id}, {Key: "role", Value: "ROLE_AGENT"}, {Key: "parts", Value: a2aTextParts(text)}}
}

func a2aStatus(state string, message A2AJSON, at time.Time) A2AJSON {
	status := A2AJSON{}
	if state != A2AStateUnspecified {
		status = append(status, A2AMember{Key: "state", Value: state})
	}
	if message != nil {
		status = append(status, A2AMember{Key: "message", Value: message})
	}
	return append(status, A2AMember{Key: "timestamp", Value: A2ATimestamp(at)})
}

func a2aArtifact(id, text string) A2AJSON {
	return A2AJSON{{Key: "artifactId", Value: id}, {Key: "name", Value: A2AResponseArtifactName}, {Key: "parts", Value: a2aTextParts(text)}}
}

// A2AStruct is a dict through google.protobuf.Struct and back: numbers become floats.
func A2AStruct(v any) any {
	switch x := v.(type) {
	case A2AJSON:
		out := make(A2AJSON, len(x))
		for i, m := range x {
			out[i] = A2AMember{Key: m.Key, Value: A2AStruct(m.Value)}
		}
		return out
	case []any:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = A2AStruct(e)
		}
		return out
	case int:
		return float64(x)
	case int64:
		return float64(x)
	case json.Number:
		f, _ := x.Float64()
		return f
	}
	return v
}

// A2ATask is to_a2a_task rendered by MessageToDict; now stands in for a row without updated_at.
func A2ATask(t A2ATaskRow, now time.Time) A2AJSON {
	state, _ := A2ATaskState(t.Status)
	at := now
	if t.UpdatedAt != nil {
		at = *t.UpdatedAt
	}
	text := ""
	var artifacts []any
	switch state {
	case A2AStateCompleted:
		if s, ok := A2AFinalText(t.Result); ok {
			text = s
			artifacts = []any{a2aArtifact(t.ID, s)}
		}
	case A2AStateFailed, A2AStateRejected:
		if t.ErrorMessage != nil && *t.ErrorMessage != "" {
			text = *t.ErrorMessage
		} else if s, ok := A2AFinalText(t.Result); ok {
			text = s
		}
	}
	var message A2AJSON
	if text != "" {
		message = a2aAgentMessage(t.ID+"-status", text)
	}
	task := A2AJSON{{Key: "id", Value: t.ID}, {Key: "contextId", Value: A2AContextID(t)}, {Key: "status", Value: a2aStatus(state, message, at)}}
	if artifacts != nil {
		task = append(task, A2AMember{Key: "artifacts", Value: artifacts})
	}
	if len(t.Metadata) > 0 {
		task = append(task, A2AMember{Key: "metadata", Value: A2AStruct(t.Metadata)})
	}
	return task
}

// A2APart is one part of a message; Kind is the oneof it sets (text, raw, url, data).
type A2APart struct {
	Kind string
	Text string
}

// A2AMessageText is message_text: the message's text parts joined.
func A2AMessageText(parts []A2APart) string {
	var b strings.Builder
	for _, p := range parts {
		if p.Kind == "text" {
			b.WriteString(p.Text)
		}
	}
	return b.String()
}

// A2AAuth is A2AAuthContext: who called an agent over A2A, and how.
type A2AAuth struct {
	Authenticated bool
	UserID        string
	WorkspaceID   string
	AgentID       string
	Permissions   []string
	AuthMethod    string
	// AgentKeyID is set when the agent's own key authenticated the call.
	AgentKeyID string
	// Metadata is user_agent and client_ip, then agent_name and agent_status.
	Metadata A2AJSON
}

// A2AMessageIn is the inbound message build_agent_task turns into a task.
type A2AMessageIn struct {
	Parts          []A2APart
	ContextID      string
	ClientMetadata A2AJSON
	AgentID        string
	Auth           A2AAuth
	UserID         string
	WorkspaceID    string
	Method         string
	RequestID      any
	Now            time.Time
}

// A2ANewTask is the task an inbound message becomes; the caller gives it an id.
type A2ANewTask struct {
	Title       string
	Description string
	Query       string
	Status      string
	Metadata    A2AJSON
}

// A2AISOTime is datetime.isoformat() of an aware UTC time.
func A2AISOTime(t time.Time) string {
	t = t.UTC()
	out := t.Format("2006-01-02T15:04:05")
	if us := t.Nanosecond() / 1000; us != 0 {
		out += fmt.Sprintf(".%06d", us)
	}
	return out + "+00:00"
}

// A2ABuildTask is build_agent_task: client metadata first, so it cannot
// overwrite the provenance and security context recorded after it.
func A2ABuildTask(in A2AMessageIn) A2ANewTask {
	text := A2AMessageText(in.Parts)
	now := A2AISOTime(in.Now)
	permissions := make([]any, len(in.Auth.Permissions))
	for i, p := range in.Auth.Permissions {
		permissions[i] = p
	}
	md := append(A2AJSON{}, in.ClientMetadata...)
	md.Set("source", "a2a")
	md.Set("a2a_method", in.Method)
	md.Set("a2a_request_id", in.RequestID)
	md.Set("auth_method", in.Auth.AuthMethod)
	md.Set("authenticated", in.Auth.Authenticated)
	md.Set("created_via", "a2a_protocol")
	md.Set("created_timestamp", now)
	md.Set("security_context", A2AJSON{
		{Key: "user_id", Value: in.UserID}, {Key: "workspace_id", Value: in.WorkspaceID},
		{Key: "permissions", Value: permissions}, {Key: "auth_timestamp", Value: now},
	})
	md.Set("monitoring", A2AJSON{
		{Key: "task_source", Value: "a2a_protocol"},
		{Key: "protocol_version", Value: "1.0"},
		{Key: "message_length", Value: utf8.RuneCountInString(text)},
		{Key: "has_message_parts", Value: len(in.Parts) > 0},
		{Key: "message_parts_count", Value: len(in.Parts)},
		{Key: "is_streaming", Value: in.Method == "SendStreamingMessage"},
		{Key: "agent_target", Value: in.AgentID},
	})
	md.Delete(A2AAgentKeyMetadata)
	if in.Auth.AgentKeyID != "" {
		md.Set(A2AAgentKeyMetadata, in.Auth.AgentKeyID)
	}
	if in.ContextID != "" {
		md.Set("a2a_context_id", in.ContextID)
	}
	if name, ok := in.Auth.Metadata.Get("agent_name"); ok {
		md.Set("target_agent_name", name)
	}
	client := A2AJSON{}
	for _, key := range []string{"user_agent", "client_ip", "forwarded_for"} {
		if v, _ := in.Auth.Metadata.Get(key); a2aTruthy(v) {
			client = append(client, A2AMember{Key: key, Value: v})
		}
	}
	if len(client) > 0 {
		md.Set("client_metadata", client)
	}
	stripped := a2aPyStrip(text)
	title, description := "A2A Message Task", "Task created from A2A message"
	if stripped != "" {
		if first := a2aPrefixRunes(a2aSplitLines(stripped)[0], 80); first != "" {
			title = first
		}
		description = stripped
	}
	return A2ANewTask{Title: title, Description: description, Query: text, Status: "submitted", Metadata: md}
}

func a2aPayload(data A2AJSON) A2AJSON {
	if p, ok := data.Get("original_data"); ok {
		if o, ok := p.(A2AJSON); ok {
			return o
		}
	}
	return data
}

// A2AEventText is event_text: the text a streamed workflow event carries.
func A2AEventText(data A2AJSON) string {
	payload := a2aPayload(data)
	for _, key := range []string{"chunk", "content", "text", "result", "final_response", "delta"} {
		if s, ok := a2aString(payload, key); ok && s != "" {
			return s
		}
	}
	return ""
}

func a2aName(payload A2AJSON, key, fallback string) string {
	if s, ok := a2aString(payload, key); ok && s != "" {
		return s
	}
	return fallback
}

func a2aPyInt(v any) (string, bool) {
	switch x := v.(type) {
	case bool:
		return a2aPyRepr(x), true
	case int:
		return strconv.Itoa(x), true
	case json.Number:
		if !a2aIsFloatLiteral(x) {
			return string(x), true
		}
	}
	return "", false
}

func a2aStep(canonical string, payload A2AJSON) string {
	tool := a2aName(payload, "tool_name", "a tool")
	switch canonical {
	case a2aTurnStarted:
		v, _ := payload.Get("iteration")
		if n, ok := a2aPyInt(v); ok {
			return "Step " + n
		}
		return "Thinking"
	case a2aToolCall:
		return "Calling " + tool
	case a2aToolResult:
		errV, _ := payload.Get("error")
		success, _ := payload.Get("success")
		if a2aTruthy(errV) || success == false {
			return tool + " failed"
		}
		return tool + " finished"
	case a2aToolProgress:
		if m, ok := a2aString(payload, "message"); ok && m != "" {
			return tool + ": " + m
		}
	case a2aDelegationStarted:
		return "Asking " + a2aName(payload, "target_agent_name", "another agent")
	case a2aDelegationCompleted:
		return a2aName(payload, "target_agent_name", "The other agent") + " answered"
	case a2aDelegationFailed:
		return a2aName(payload, "target_agent_name", "The other agent") + " could not answer"
	case a2aContextCompacted:
		return "Summarising the earlier conversation"
	case a2aTaskAwaitingInfrastructure:
		return "Waiting for a service to come back"
	}
	return ""
}

func a2aInterruption(canonical string, payload A2AJSON) (string, bool) {
	switch canonical {
	case a2aInputRequest:
		return a2aName(payload, "question", "The agent needs more information"), true
	case a2aApprovalRequested:
		return "Waiting for approval to run " + a2aName(payload, "tool_name", "a tool"), true
	case a2aTaskAwaitingContinuation:
		return a2aName(payload, "message", "The run reached a limit and waits for a decision"), true
	}
	return "", false
}

// A2AStream is one event of an A2A stream: what it says, and how to render it.
type A2AStream struct {
	TaskID    string
	ContextID string
	Now       time.Time
	// NewID is uuid4().hex, the id of a status message.
	NewID func() string
}

func (s A2AStream) statusUpdate(state, text, event string) A2AJSON {
	var message A2AJSON
	if text != "" {
		message = a2aAgentMessage(s.NewID(), text)
	}
	update := A2AJSON{{Key: "taskId", Value: s.TaskID}, {Key: "contextId", Value: s.ContextID}, {Key: "status", Value: a2aStatus(state, message, s.Now)}}
	if event != "" {
		update = append(update, A2AMember{Key: "metadata", Value: A2AJSON{{Key: "agentarea_event", Value: event}}})
	}
	return A2AJSON{{Key: "statusUpdate", Value: update}}
}

func (s A2AStream) artifactUpdate(text string, lastChunk bool) A2AJSON {
	update := A2AJSON{{Key: "taskId", Value: s.TaskID}, {Key: "contextId", Value: s.ContextID}, {Key: "artifact", Value: a2aArtifact(s.TaskID, text)}}
	if lastChunk {
		update = append(update, A2AMember{Key: "lastChunk", Value: true})
	}
	return A2AJSON{{Key: "artifactUpdate", Value: update}}
}

// A2AWorkflowEvent is workflow_event_to_a2a: one task event as StreamResponse
// results; done says the stream is over.
func (s A2AStream) A2AWorkflowEvent(eventType string, data A2AJSON) (events []A2AJSON, done bool) {
	canonical := A2ACanonicalType(eventType)
	payload := a2aPayload(data)
	if state, ok := a2aTerminalEvents()[canonical]; ok {
		if state == A2AStateCompleted {
			if text := A2AEventText(data); text != "" {
				events = append(events, s.artifactUpdate(text, true))
			}
		}
		return append(events, s.statusUpdate(state, "", "")), true
	}
	if reason, ok := a2aInterruption(canonical, payload); ok {
		return []A2AJSON{s.statusUpdate(A2AStateInputRequired, reason, canonical)}, true
	}
	if canonical == a2aLLMChunk {
		text := A2AEventText(data)
		if text == "" {
			return nil, false
		}
		return []A2AJSON{s.artifactUpdate(text, false)}, false
	}
	step := a2aStep(canonical, payload)
	event := ""
	if step != "" {
		event = canonical
	}
	return []A2AJSON{s.statusUpdate(A2AStateWorking, step, event)}, false
}
