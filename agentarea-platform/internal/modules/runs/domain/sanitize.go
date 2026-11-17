package domain

import (
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"unicode/utf8"
)

// MaxEventStringChars bounds one string in the event log (redaction.py).
const MaxEventStringChars = 2000

const maxEventItems = 100

func eventContentKey(name string) bool {
	switch name {
	case "base64", "blob", "body", "bytes", "code", "content", "contents", "data", "file_content",
		"payload", "result", "script", "stderr", "stdout":
		return true
	}
	return false
}

func eventSecretName(name string) bool {
	for _, fragment := range []string{"api_key", "authorization", "credential", "password", "secret", "token"} {
		if strings.Contains(name, fragment) {
			return true
		}
	}
	return false
}

func eventOmission(size int) string {
	return fmt.Sprintf("[omitted from event log: %d units]", size)
}

func looksBinaryOrBulk(s string) bool {
	n := utf8.RuneCountInString(s)
	if n > MaxEventStringChars || base64Like(s) {
		return true
	}
	if strings.ContainsRune(s, 0) {
		return true
	}
	controls := 0
	for _, r := range s {
		if r < 32 && r != '\n' && r != '\r' && r != '\t' {
			controls++
		}
	}
	return n > 0 && float64(controls)/float64(n) > 0.02
}

func base64Like(s string) bool {
	return len(s) >= 256 && regexp.MustCompile(`^[A-Za-z0-9+/=_-]+$`).MatchString(s)
}

// SanitizeToolEventValue bounds event data without file bodies, secrets or
// binary blobs (sanitize_tool_event_value). Activities and the model still get
// the original values. Keys are visited in sorted order so a run's events are
// the same on every replay.
func SanitizeToolEventValue(value any, fieldName string) any {
	return sanitize(value, fieldName, 0)
}

func sanitize(value any, fieldName string, depth int) any {
	if depth >= 10 {
		return "[nested value omitted from event log]"
	}
	name := strings.ToLower(fieldName)
	if eventSecretName(name) {
		return "[redacted]"
	}
	if eventContentKey(name) || name == "command" {
		switch v := value.(type) {
		case string:
			return eventOmission(utf8.RuneCountInString(v))
		case []byte:
			return eventOmission(len(v))
		}
		return eventOmission(0)
	}
	switch v := value.(type) {
	case nil, bool, int, int64, float64, json.Number:
		return v
	case string:
		if looksBinaryOrBulk(v) {
			return eventOmission(utf8.RuneCountInString(v))
		}
		return v
	case []byte:
		return eventOmission(len(v))
	case map[string]any:
		keys := make([]string, 0, len(v))
		for k := range v {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		if len(keys) > maxEventItems {
			keys = keys[:maxEventItems]
		}
		out := make(map[string]any, len(keys))
		for _, k := range keys {
			out[k] = sanitize(v[k], k, depth+1)
		}
		return out
	case []any:
		n := min(len(v), maxEventItems)
		out := make([]any, n)
		for i := range n {
			out[i] = sanitize(v[i], "", depth+1)
		}
		return out
	case []string:
		n := min(len(v), maxEventItems)
		out := make([]any, n)
		for i := range n {
			out[i] = sanitize(v[i], "", depth+1)
		}
		return out
	case []map[string]any:
		n := min(len(v), maxEventItems)
		out := make([]any, n)
		for i := range n {
			out[i] = sanitize(v[i], "", depth+1)
		}
		return out
	}
	return fmt.Sprintf("[%T omitted from event log]", value)
}

// SanitizeToolResultData sanitizes a tool.result event's data as a whole.
func SanitizeToolResultData(data map[string]any) map[string]any {
	structured, has := data["structured_content"]
	rest := make(map[string]any, len(data))
	for k, v := range data {
		if k != "structured_content" {
			rest[k] = v
		}
	}
	out, _ := sanitize(rest, "", 0).(map[string]any)
	// An MCP App parses structured_content against its own schema, so it stays
	// whole; the MCP call already caps its size.
	if has && structured != nil && out != nil {
		out["structured_content"] = RevealToolValue(structured, "")
	}
	return out
}

// BoundedLLMContent keeps an llm.call.completed display text useful but bounded.
func BoundedLLMContent(s string) string {
	n := utf8.RuneCountInString(s)
	if n <= MaxEventStringChars {
		return s
	}
	runes := []rune(s)
	return fmt.Sprintf("%s\n[truncated %d characters from event log]", string(runes[:MaxEventStringChars]), n-MaxEventStringChars)
}

// EnsureTerminalMessage gives terminal task events a user-facing message
// (and reason for failed and cancelled); an existing message is kept.
func EnsureTerminalMessage(eventType string, data map[string]any) map[string]any {
	if !Terminal(eventType) {
		return data
	}
	if eventType == EventTaskCompleted {
		if truthy(data["message"]) {
			return data
		}
		final := firstTruthyString(data["final_response"], data["result"])
		if final == "" {
			final = "Task completed."
		}
		data["message"] = final
		return data
	}
	reason := firstTruthyString(data["reason"], data["error"], data["blocked_reason"], data["error_type"])
	if reason == "" {
		if eventType == EventTaskFailed {
			reason = "Task failed."
		} else {
			reason = "Task cancelled."
		}
	}
	if _, ok := data["reason"]; !ok {
		data["reason"] = reason
	}
	if !truthy(data["message"]) {
		data["message"] = reason
	}
	return data
}

func truthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case string:
		return x != ""
	case bool:
		return x
	case int:
		return x != 0
	case int64:
		return x != 0
	case float64:
		return x != 0
	case *string:
		return x != nil && *x != ""
	}
	return true
}

func firstTruthyString(values ...any) string {
	for _, v := range values {
		if !truthy(v) {
			continue
		}
		switch x := v.(type) {
		case string:
			return x
		case *string:
			return *x
		default:
			return fmt.Sprint(x)
		}
	}
	return ""
}
