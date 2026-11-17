package service

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"sort"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
)

// pyStr is str(value) of a JSON value as Python holds it.
func pyStr(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return pyRepr(v)
}

// pyRepr is repr(value) of a JSON value as Python holds it.
func pyRepr(v any) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case bool:
		if x {
			return "True"
		}
		return "False"
	case string:
		return pyReprStr(x)
	case json.Number:
		return string(x)
	case wirejson.Float:
		return wirejson.FormatFloat(float64(x))
	case []any:
		parts := make([]string, len(x))
		for i, e := range x {
			parts[i] = pyRepr(e)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case wirejson.Object:
		parts := make([]string, len(x))
		for i, m := range x {
			parts[i] = pyReprStr(m.Key) + ": " + pyRepr(m.Value)
		}
		return "{" + strings.Join(parts, ", ") + "}"
	}
	raw, _ := json.Marshal(v)
	return string(raw)
}

// pyReprStr is repr(str): single quotes unless the text holds one and no double quote.
func pyReprStr(s string) string {
	quote := byte('\'')
	if strings.Contains(s, "'") && !strings.Contains(s, "\"") {
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
			b.WriteString(`\x`)
			b.WriteString(hex.EncodeToString([]byte{byte(r)}))
		default:
			b.WriteRune(r)
		}
	}
	b.WriteByte(quote)
	return b.String()
}

// sortedKeys is v with every object's keys sorted (json.dumps(sort_keys=True)).
func sortedKeys(v any) any {
	switch x := v.(type) {
	case wirejson.Object:
		out := make(wirejson.Object, len(x))
		for i, m := range x {
			out[i] = wirejson.Member{Key: m.Key, Value: sortedKeys(m.Value)}
		}
		sort.SliceStable(out, func(i, j int) bool { return out[i].Key < out[j].Key })
		return out
	case []any:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = sortedKeys(e)
		}
		return out
	}
	return v
}

// sha256Dumps is sha256 of json.dumps(v, sort_keys=True), hex.
func sha256Dumps(v any) (string, error) {
	raw, err := wirejson.Marshal(sortedKeys(v), wirejson.Dumps)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:]), nil
}
