package domain

import (
	"encoding/json"
	"fmt"
	"math/big"
	"regexp"
	"sort"
	"strings"
	"time"
	"unicode"
)

// TaskDefReservedParameters are RESERVED_TASK_PARAMETERS: only the trigger that received an event writes them.
func TaskDefReservedParameters() []string {
	return []string{"delivery_address", "follow_up_message", "session", "trigger_event", "trigger_event_file"}
}

var taskDefEffectShape = regexp.MustCompile(`^[a-z][a-z_-]{0,15}\n?\z`)

// TaskDefMaxReasoningTokens is MAX_REASONING_MAX_TOKENS.
const TaskDefMaxReasoningTokens = 1<<31 - 1

// TaskDefCheckParameters runs the parameters validators of the task DTOs in
// order (reserved keys, model_override, reasoning); "" when they pass. get
// reads a key of the parameters object.
func TaskDefCheckParameters(keys []string, get func(string) (any, bool)) string {
	reserved := map[string]bool{}
	for _, k := range TaskDefReservedParameters() {
		reserved[k] = true
	}
	var hit []string
	seen := map[string]bool{}
	for _, k := range keys {
		if reserved[k] && !seen[k] {
			hit = append(hit, k)
			seen[k] = true
		}
	}
	if len(hit) > 0 {
		sort.Strings(hit)
		return strings.Join(hit, ", ") + " is set by the trigger that received the event and cannot be supplied"
	}
	if v, ok := get("model_override"); ok && v != nil && v != "" {
		s, isStr := v.(string)
		if !isStr || !TaskDefPythonUUID(s) {
			return "model_override must be a model instance id"
		}
	}
	effect, msg := taskDefEffort(get)
	if msg != "" {
		return msg
	}
	tokens, msg := taskDefMaxTokens(get)
	if msg != "" {
		return msg
	}
	if effect && tokens {
		return ErrReasoningConflict.Error()
	}
	return ""
}

func taskDefEffort(get func(string) (any, bool)) (set bool, msg string) {
	v, ok := get("reasoning_effort")
	if !ok || v == nil || v == "" {
		return false, ""
	}
	s, isStr := v.(string)
	if !isStr || !taskDefEffectShape.MatchString(s) {
		return false, "reasoning_effort must be a level name such as low or high"
	}
	return true, ""
}

func taskDefMaxTokens(get func(string) (any, bool)) (set bool, msg string) {
	v, ok := get("reasoning_max_tokens")
	if !ok || v == nil {
		return false, ""
	}
	n, isNum := v.(json.Number)
	var i *big.Int
	if isNum {
		i, isNum = new(big.Int).SetString(string(n), 10)
	}
	if !isNum || i.Sign() <= 0 {
		return false, "reasoning_max_tokens must be a positive integer"
	}
	if i.Cmp(big.NewInt(TaskDefMaxReasoningTokens)) > 0 {
		return false, fmt.Sprintf("reasoning_max_tokens must be at most %d", TaskDefMaxReasoningTokens)
	}
	return true, ""
}

// TaskDefPythonUUID is whether uuid.UUID(s) accepts s.
func TaskDefPythonUUID(s string) bool {
	h := strings.ReplaceAll(strings.ReplaceAll(s, "urn:", ""), "uuid:", "")
	h = strings.ReplaceAll(strings.Trim(h, "{}"), "-", "")
	if len([]rune(h)) != 32 {
		return false
	}
	h = strings.TrimFunc(h, unicode.IsSpace)
	h = strings.TrimPrefix(h, "+")
	if len(h) > 2 && (h[:2] == "0x" || h[:2] == "0X") {
		h = strings.TrimPrefix(h[2:], "_")
	}
	if h == "" || h[0] == '_' || h[len(h)-1] == '_' || strings.Contains(h, "__") {
		return false
	}
	for _, r := range strings.ReplaceAll(h, "_", "") {
		if !strings.ContainsRune("0123456789abcdefABCDEF", r) {
			return false
		}
	}
	return true
}

// TaskDefISOZ is utc_isoformat: a naive value read as UTC, microseconds only when set, Z for +00:00.
func TaskDefISOZ(t time.Time) string {
	t = t.UTC()
	s := t.Format("2006-01-02T15:04:05")
	if us := t.Nanosecond() / 1000; us != 0 {
		s += fmt.Sprintf(".%06d", us)
	}
	return s + "Z"
}
