package domain

import (
	"encoding/json"
	"fmt"
	"math/big"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

// StoredEvent is an event row of the task log as the record activity reads it.
type StoredEvent struct {
	ID        string
	Type      string
	Timestamp time.Time
	Data      map[string]any
}

// RowEvent is an event row as the workflow event it records; false for any other row.
func RowEvent(e Entry, now time.Time) (StoredEvent, bool) {
	if e.Kind != KindEvent {
		return StoredEvent{}, false
	}
	ts := now
	if e.OccurredAt != nil {
		ts = *e.OccurredAt
	}
	data := e.Meta
	if data == nil {
		data = map[string]any{}
	}
	return StoredEvent{ID: e.EventID, Type: e.Name, Timestamp: ts, Data: data}, true
}

// EndedStatus reports the statuses a run ends in; entering one stamps completed_at.
func EndedStatus(s string) bool {
	return s == "blocked" || s == "completed" || s == "failed" || s == "cancelled"
}

func errorClearing(s string) bool { return s == "running" || s == "completed" }

// ResumePoint is where a closed task's conversation stands.
type ResumePoint struct {
	NextSeq          int64
	CurrentIteration int
	ToolCallsUsed    int
	TokensUsed       int64
	LastPromptTokens int64
}

// StatusUpdate is the status a run records for its task; costs are decimal text.
type StatusUpdate struct {
	Status          string
	Response        string
	Artifacts       []string
	ValidationState string
	ErrorMessage    string
	FailureReason   string
	TotalCost       *string
	OwnCost         *string
	TokensUsed      *int64
	Resume          *ResumePoint
	RunStartedAt    *time.Time
}

// Outcome is what a status update sets on the task row (TaskOutcome); Result
// keeps Python's key order because tasks.result is a json column.
// SetError false leaves the row's error alone; Error nil with SetError clears it.
type Outcome struct {
	Status string
	// Result nil leaves the row's result alone.
	Result        Ordered
	SetError      bool
	Error         *string
	MetadataPatch map[string]any
}

// OutcomeOf is task_outcome: the result JSON the task list reads, the error,
// and the metadata patch (resume snapshot, failure reason).
func OutcomeOf(u StatusUpdate) Outcome {
	var result Ordered
	hasResult := false
	switch {
	case u.Response != "":
		hasResult = true
		result = Ordered{{Key: "response", Value: u.Response}}
		if u.Artifacts != nil {
			result = append(result, KV{Key: "artifacts", Value: slices.Clone(u.Artifacts)})
		}
		result = append(result, KV{Key: "validation_state", Value: u.ValidationState})
	case u.TotalCost != nil || u.OwnCost != nil:
		hasResult = true
		result = Ordered{}
	}
	if hasResult {
		if u.TotalCost != nil {
			result = append(result, KV{Key: "total_cost", Value: *u.TotalCost})
		}
		if u.OwnCost != nil {
			result = append(result, KV{Key: "own_cost", Value: *u.OwnCost})
		}
		if u.TokensUsed != nil {
			result = append(result, KV{Key: "tokens_used", Value: *u.TokensUsed})
		}
	}
	patch := map[string]any{}
	if r := u.Resume; r != nil {
		patch["conversation_resume"] = map[string]any{
			"head_seqs": []any{}, "tail_start": 0, "next_seq": r.NextSeq,
			"current_iteration": r.CurrentIteration, "tool_calls_used": r.ToolCallsUsed,
			"tokens_used": r.TokensUsed, "last_prompt_tokens": r.LastPromptTokens,
		}
	}
	if u.FailureReason != "" {
		patch["failure_reason"] = u.FailureReason
	} else if errorClearing(u.Status) {
		patch["failure_reason"] = nil
	}
	o := Outcome{Status: u.Status, Result: result}
	if len(patch) > 0 {
		o.MetadataPatch = patch
	}
	switch {
	case u.ErrorMessage != "":
		msg := u.ErrorMessage
		o.SetError, o.Error = true, &msg
	case errorClearing(u.Status):
		o.SetError = true
	}
	return o
}

// ChangesStatus reports whether writing o moves the task to a status it does not have yet.
func ChangesStatus(current string, o *Outcome) bool { return o != nil && o.Status != current }

// Storable replaces, everywhere in a JSON value (keys included), what
// Postgres text cannot hold (NUL, invalid UTF-8) with U+FFFD (pg_storable).
func Storable(v any) any {
	switch x := v.(type) {
	case string:
		return StorableText(x)
	case map[string]any:
		out := make(map[string]any, len(x))
		for k, item := range x {
			out[StorableText(k)] = Storable(item)
		}
		return out
	case []any:
		out := make([]any, len(x))
		for i, item := range x {
			out[i] = Storable(item)
		}
		return out
	}
	return v
}

// StorableText is Storable for one string.
func StorableText(s string) string {
	if utf8.ValidString(s) && !strings.ContainsRune(s, 0) {
		return s
	}
	return strings.ReplaceAll(strings.ToValidUTF8(s, "�"), "\x00", "�")
}

// StorableMap is Storable for an event's data.
func StorableMap(m map[string]any) map[string]any {
	if m == nil {
		return nil
	}
	out, _ := Storable(m).(map[string]any)
	return out
}

// Audit actions a run's tool events stand for (tool_audit.py).
const (
	AuditToolCallAllowed          = "tool.call.allowed"
	AuditToolCallDenied           = "tool.call.denied"
	AuditToolCallApprovalRequired = "tool.call.approval_required"
	AuditApprovalApproved         = "approval.approved"
	AuditApprovalDenied           = "approval.denied"
)

// AuditLine is one audit row stored once under its event's id.
type AuditLine struct {
	EventID   string
	Action    string
	TaskID    string
	ActorType string
	ActorID   string
	Metadata  map[string]any
}

// ArgumentKeys are the names of a tool call's arguments, never their values.
func ArgumentKeys(args any) []string {
	m, ok := args.(map[string]any)
	if !ok {
		return []string{}
	}
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	slices.Sort(keys)
	return keys
}

// ToolAudit is the audit row a stored event stands for (tool_audit_entry +
// audit_line); requestedBy stands in as the actor when the event names none.
func ToolAudit(e StoredEvent, requestedBy string) (AuditLine, bool) {
	d := e.Data
	taskID := pyStr(d["task_id"])
	agentID := d["agent_id"]
	base := map[string]any{"tool": d["tool_name"], "task_id": taskID, "agent_id": agentID, "tool_call_id": d["tool_call_id"]}
	actor, _ := d["actor"].(map[string]any)
	asAgent := func(action string, extra map[string]any) (AuditLine, bool) {
		meta := merge(base, extra)
		if actor != nil {
			return auditLine(e.ID, action, taskID, pyStr(actor["type"]), pyStr(actor["id"]), meta, requestedBy), true
		}
		id := ""
		if present(agentID) {
			id = pyStr(agentID)
		}
		return auditLine(e.ID, action, taskID, "agent", id, meta, requestedBy), true
	}
	switch {
	case e.Type == EventToolCall:
		return asAgent(AuditToolCallAllowed, map[string]any{"decision": "allowed", "argument_keys": ArgumentKeys(d["arguments"])})
	case e.Type == EventDelegationStarted:
		return asAgent(AuditToolCallAllowed, map[string]any{"decision": "allowed", "delegate_agent_id": d["target_agent_id"]})
	case e.Type == EventToolResult && present(d["denied_by_policy"]):
		return asAgent(AuditToolCallDenied, map[string]any{"decision": "denied", "reason": d["error"]})
	case e.Type == EventApprovalRequested:
		return asAgent(AuditToolCallApprovalRequired, map[string]any{
			"decision": "approval_required", "reason": d["message"], "escalation_id": d["escalation_id"],
			"approvers": d["approvers"], "argument_keys": ArgumentKeys(d["arguments"]),
		})
	case e.Type == EventApprovalDecided:
		raw, ok := d["approved"]
		if !ok {
			return AuditLine{}, false
		}
		approved := present(raw)
		action, decision := AuditApprovalDenied, "denied"
		if approved {
			action, decision = AuditApprovalApproved, "approved"
		}
		actorType, actorID := "system", ""
		if present(d["approved_by"]) {
			actorType, actorID = "user", pyStr(d["approved_by"])
		}
		meta := merge(base, map[string]any{"decision": decision, "comment": d["comment"], "escalation_id": d["escalation_id"]})
		return auditLine(e.ID, action, taskID, actorType, actorID, meta, requestedBy), true
	}
	return AuditLine{}, false
}

func auditLine(eventID, action, taskID, actorType, actorID string, meta map[string]any, requestedBy string) AuditLine {
	if actorID == "" {
		actorID = requestedBy
	}
	kept := map[string]any{}
	for k, v := range meta {
		if v != nil {
			kept[k] = v
		}
	}
	kept["requested_by"] = requestedBy
	return AuditLine{EventID: eventID, Action: action, TaskID: taskID, ActorType: actorType, ActorID: actorID, Metadata: kept}
}

func merge(a, b map[string]any) map[string]any {
	out := make(map[string]any, len(a)+len(b))
	for k, v := range a {
		out[k] = v
	}
	for k, v := range b {
		out[k] = v
	}
	return out
}

// present is Python truthiness for a JSON value.
func present(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case string:
		return x != ""
	case bool:
		return x
	case float64:
		return x != 0
	case int:
		return x != 0
	case int64:
		return x != 0
	case json.Number:
		r, ok := new(big.Rat).SetString(string(x))
		return !ok || r.Sign() != 0
	case map[string]any:
		return len(x) > 0
	case []any:
		return len(x) > 0
	}
	return true
}

// pyStr is str(value) for the scalars event data holds.
func pyStr(v any) string {
	switch x := v.(type) {
	case nil:
		return ""
	case string:
		return x
	case bool:
		if x {
			return "True"
		}
		return "False"
	case float64:
		if x == float64(int64(x)) {
			return strconv.FormatInt(int64(x), 10)
		}
		return strconv.FormatFloat(x, 'f', -1, 64)
	}
	return fmt.Sprint(v)
}

// Amount reads a money value from event data as decimal text; absent or unreadable is zero.
func Amount(v any) (string, *big.Rat) {
	var s string
	switch x := v.(type) {
	case nil:
		return "0", new(big.Rat)
	case string:
		s = strings.TrimSpace(x)
	case float64:
		s = strconv.FormatFloat(x, 'f', -1, 64)
	case int:
		s = strconv.Itoa(x)
	case int64:
		s = strconv.FormatInt(x, 10)
	case json.Number:
		s = string(x)
	case fmt.Stringer:
		s = x.String()
	default:
		return "0", new(big.Rat)
	}
	r, ok := new(big.Rat).SetString(s)
	if !ok {
		return "0", new(big.Rat)
	}
	return s, r
}

func optionalAmount(v any) *string {
	if v == nil {
		return nil
	}
	s, _ := Amount(v)
	return &s
}
