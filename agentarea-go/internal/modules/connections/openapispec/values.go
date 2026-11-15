// Package openapispec reads OpenAPI 3.x documents into the operations an
// OpenAPI connection serves, builds and reads their HTTP calls, and checks
// the URLs and key forms a connection is made with (agentarea_openapi and
// the agents SDK's openapi_tool).
package openapispec

import (
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"strings"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
)

// Error is a document or input the parser refuses: Python's ValueError, a 400.
type Error struct{ Msg string }

func (e *Error) Error() string { return e.Msg }

func errorf(format string, args ...any) error { return &Error{Msg: fmt.Sprintf(format, args...)} }

// asObject reads a JSON object in its key order. A decoded map (a jsonb
// column read elsewhere) is read in jsonb's own order: shorter keys first,
// then bytewise, which is the order Python sees after a database round trip.
func asObject(v any) (wirejson.Object, bool) {
	switch t := v.(type) {
	case wirejson.Object:
		return t, true
	case map[string]any:
		keys := make([]string, 0, len(t))
		for k := range t {
			keys = append(keys, k)
		}
		sort.Slice(keys, func(i, j int) bool {
			if len(keys[i]) != len(keys[j]) {
				return len(keys[i]) < len(keys[j])
			}
			return keys[i] < keys[j]
		})
		out := make(wirejson.Object, len(keys))
		for i, k := range keys {
			out[i] = wirejson.Member{Key: k, Value: t[k]}
		}
		return out, true
	}
	return nil, false
}

func isObject(v any) bool {
	_, ok := asObject(v)
	return ok
}

// truthy is Python's truth value of a JSON value.
func truthy(v any) bool {
	switch t := v.(type) {
	case nil:
		return false
	case bool:
		return t
	case string:
		return t != ""
	case json.Number:
		f, err := t.Float64()
		return err != nil || f != 0
	case wirejson.Float:
		return t != 0
	case float64:
		return t != 0
	case int:
		return t != 0
	case int64:
		return t != 0
	case []any:
		return len(t) > 0
	case wirejson.Object:
		return len(t) > 0
	case map[string]any:
		return len(t) > 0
	}
	return true
}

// or is Python's `v or fallback`.
func or(v, fallback any) any {
	if truthy(v) {
		return v
	}
	return fallback
}

// get is dict.get(key, def).
func get(o wirejson.Object, key string, def any) any {
	if v, ok := o.Get(key); ok {
		return v
	}
	return def
}

func has(o wirejson.Object, key string) bool {
	_, ok := o.Get(key)
	return ok
}

// repr is Python's repr of a JSON value, for messages.
func repr(v any) string {
	switch t := v.(type) {
	case nil:
		return "None"
	case bool:
		if t {
			return "True"
		}
		return "False"
	case string:
		return pyStr(t)
	case json.Number:
		return t.String()
	case wirejson.Float:
		return wirejson.FormatFloat(float64(t))
	case float64:
		return wirejson.FormatFloat(t)
	case int:
		return strconv.Itoa(t)
	case []any:
		parts := make([]string, len(t))
		for i, x := range t {
			parts[i] = repr(x)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	}
	if o, ok := asObject(v); ok {
		parts := make([]string, len(o))
		for i, m := range o {
			parts[i] = pyStr(m.Key) + ": " + repr(m.Value)
		}
		return "{" + strings.Join(parts, ", ") + "}"
	}
	return fmt.Sprint(v)
}

// pyStr is repr(str): single quotes unless the text holds one and no double quote.
func pyStr(s string) string {
	quote := byte('\'')
	if strings.ContainsRune(s, '\'') && !strings.ContainsRune(s, '"') {
		quote = '"'
	}
	var b strings.Builder
	b.WriteByte(quote)
	for _, r := range s {
		switch {
		case r == '\\':
			b.WriteString(`\\`)
		case r == rune(quote):
			b.WriteByte('\\')
			b.WriteRune(r)
		case r == '\n':
			b.WriteString(`\n`)
		case r == '\r':
			b.WriteString(`\r`)
		case r == '\t':
			b.WriteString(`\t`)
		case r < 0x20 || r == 0x7f:
			fmt.Fprintf(&b, `\x%02x`, r)
		default:
			b.WriteRune(r)
		}
	}
	b.WriteByte(quote)
	return b.String()
}

// Plain turns a parsed document into maps and slices, numbers as written.
func Plain(v any) any {
	switch t := v.(type) {
	case wirejson.Object:
		out := make(map[string]any, len(t))
		for _, m := range t {
			out[m.Key] = Plain(m.Value)
		}
		return out
	case map[string]any:
		out := make(map[string]any, len(t))
		for k, x := range t {
			out[k] = Plain(x)
		}
		return out
	case []any:
		out := make([]any, len(t))
		for i, x := range t {
			out[i] = Plain(x)
		}
		return out
	case wirejson.Float:
		return json.Number(wirejson.FormatFloat(float64(t)))
	}
	return v
}

// Truthy is Python's truth value of a document value.
func Truthy(v any) bool { return truthy(v) }
