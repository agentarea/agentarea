package domain

import (
	"encoding/json"
	"slices"
	"time"
)

// Task log row kinds (task_conversation_entries.kind).
const (
	KindMessage    = "message"
	KindCompaction = "compaction"
	KindEvent      = "event"
)

// BodyOffloadBytes is the UTF-8 size above which a row body is stored by reference.
const BodyOffloadBytes = 64 * 1024

// ToolCallsRef names, in a row's meta, the reference of tool calls stored outside it.
const ToolCallsRef = "tool_calls_ref"

// ToolCall is one call a model turn asked for; Arguments is the model's JSON text.
type ToolCall struct {
	ID        string
	Name      string
	Arguments string
}

// ImageRef is an image kept with the task's offloaded context.
type ImageRef struct {
	ID       string `json:"id"`
	MimeType string `json:"mime_type"`
	Size     int64  `json:"size"`
}

// Entry is one row of a task's log (ConversationEntry).
type Entry struct {
	Seq         int64
	EventID     string
	Kind        string
	Role        string
	Content     string
	ToolCalls   []ToolCall
	ToolCallID  string
	Name        string
	Attachments []ImageRef
	Meta        map[string]any
	Iteration   *int
	ExecutionID string
	OccurredAt  *time.Time
	BodyRef     string
}

type wireFunction struct {
	Name      string `json:"name"`
	Arguments string `json:"arguments"`
}

type wireToolCall struct {
	ID       string       `json:"id"`
	Type     string       `json:"type"`
	Function wireFunction `json:"function"`
}

// ToolCallsJSON is tool calls as the log stores them, in the OpenAI shape.
func ToolCallsJSON(calls []ToolCall) []any {
	if calls == nil {
		return nil
	}
	out := make([]any, 0, len(calls))
	for _, c := range calls {
		out = append(out, map[string]any{
			"id": c.ID, "type": "function",
			"function": map[string]any{"name": c.Name, "arguments": c.Arguments},
		})
	}
	return out
}

// ParseToolCalls reads stored tool calls; a call without an id or function is kept with what it has.
func ParseToolCalls(raw []byte) ([]ToolCall, error) {
	if len(raw) == 0 || string(raw) == "null" {
		return nil, nil
	}
	var wire []wireToolCall
	if err := json.Unmarshal(raw, &wire); err != nil {
		return nil, err
	}
	out := make([]ToolCall, 0, len(wire))
	for _, w := range wire {
		out = append(out, ToolCall{ID: w.ID, Name: w.Function.Name, Arguments: w.Function.Arguments})
	}
	return out, nil
}

// AnsweredMessages keeps the entries a chat model accepts in order: a tool
// result only as the answer to a call of the assistant turn right before it,
// and a turn only with every call answered.
func AnsweredMessages(entries []Entry) []Entry {
	var valid []Entry
	open := map[string]bool{}
	turnStart := 0
	for _, e := range entries {
		if e.Role == "tool" {
			if open[e.ToolCallID] {
				valid = append(valid, e)
				delete(open, e.ToolCallID)
			}
			continue
		}
		if len(open) > 0 {
			valid = valid[:turnStart]
			open = map[string]bool{}
		}
		if e.Role == "assistant" && len(e.ToolCalls) > 0 {
			ids := map[string]bool{}
			complete := true
			for _, c := range e.ToolCalls {
				if c.ID == "" {
					complete = false
					break
				}
				ids[c.ID] = true
			}
			if !complete {
				continue
			}
			open = ids
			turnStart = len(valid)
		}
		valid = append(valid, e)
	}
	if len(open) > 0 {
		valid = valid[:turnStart]
	}
	return valid
}

// ModelWindow is what the model sees: the first system prompt, the latest
// compaction, the answered messages after it. Event rows never enter.
func ModelWindow(entries []Entry) []Entry {
	var ordered []Entry
	for _, e := range entries {
		if e.Kind == KindMessage || e.Kind == KindCompaction {
			ordered = append(ordered, e)
		}
	}
	slices.SortStableFunc(ordered, func(a, b Entry) int {
		switch {
		case a.Seq < b.Seq:
			return -1
		case a.Seq > b.Seq:
			return 1
		}
		return 0
	})
	var system, compaction *Entry
	for i := range ordered {
		if ordered[i].Kind == KindMessage && ordered[i].Role == "system" {
			system = &ordered[i]
			break
		}
	}
	for i := len(ordered) - 1; i >= 0; i-- {
		if ordered[i].Kind == KindCompaction {
			compaction = &ordered[i]
			break
		}
	}
	start := int64(-1)
	if compaction != nil {
		start = compaction.Seq
	}
	var rest []Entry
	for _, e := range ordered {
		if e.Kind == KindMessage && e.Seq > start && (system == nil || e.Seq != system.Seq) {
			rest = append(rest, e)
		}
	}
	var head []Entry
	if system != nil {
		head = append(head, *system)
	}
	if compaction != nil {
		head = append(head, *compaction)
	}
	return append(head, AnsweredMessages(rest)...)
}

// FeedBodies are the full tool arguments and results of a run, by tool call id.
type FeedBodies struct {
	Results   map[string]string
	Arguments map[string]any
}

// BodiesOf collects the bodies the run's messages hold; a body stored outside its row is not here.
func BodiesOf(entries []Entry) FeedBodies {
	b := FeedBodies{Results: map[string]string{}, Arguments: map[string]any{}}
	for _, e := range entries {
		if e.Kind != KindMessage {
			continue
		}
		if e.Role == "tool" && e.ToolCallID != "" && e.BodyRef == "" {
			b.Results[e.ToolCallID] = e.Content
		}
		if e.Role == "assistant" {
			for _, c := range e.ToolCalls {
				if c.ID == "" {
					continue
				}
				var parsed any
				if err := json.Unmarshal([]byte(c.Arguments), &parsed); err != nil {
					b.Arguments[c.ID] = c.Arguments
					continue
				}
				b.Arguments[c.ID] = parsed
			}
		}
	}
	return b
}

// FeedEvent is a log row as the task feed shows it: an event row is its event
// (with tool bodies from bodies), a person's message is message.received;
// every other row is left out.
func FeedEvent(e Entry, bodies *FeedBodies) (string, map[string]any, bool) {
	switch {
	case e.Kind == KindEvent:
		data := make(map[string]any, len(e.Meta)+2)
		for k, v := range e.Meta {
			data[k] = v
		}
		callID, isString := data["tool_call_id"].(string)
		if bodies != nil && isString {
			if e.Name == EventToolCall || e.Name == EventToolResult {
				if args, ok := bodies.Arguments[callID]; ok {
					data["arguments"] = SanitizeToolEventValue(args, "")
				}
			}
			if e.Name == EventToolResult {
				if result, ok := bodies.Results[callID]; ok {
					data["result"] = SanitizeToolEventValue(result, "result")
				}
			}
		}
		return e.Name, data, e.Name != ""
	case e.Kind == KindMessage && e.Role == "user":
		attachments := []any{}
		for _, a := range e.Attachments {
			attachments = append(attachments, map[string]any{"id": a.ID, "mime_type": a.MimeType, "size": a.Size})
		}
		data := map[string]any{
			"content": e.Content, "attachments": attachments,
			"iteration": intOrNil(e.Iteration), "execution_id": strOrNil(e.ExecutionID),
		}
		if e.BodyRef != "" {
			data["content_stored_separately"] = true
		}
		return EventMessageReceived, data, true
	}
	return "", nil, false
}

// Recallable reports the types the task log keeps: every stored event type.
func Recallable(t string) bool { return KnownEventType(t) && !LiveOnly(t) }

func intOrNil(p *int) any {
	if p == nil {
		return nil
	}
	return *p
}

func strOrNil(s string) any {
	if s == "" {
		return nil
	}
	return s
}
