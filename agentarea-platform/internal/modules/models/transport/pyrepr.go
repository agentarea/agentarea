package transport

import (
	"encoding/json"
	"fmt"
	"math"
	"slices"
	"strings"
	"unicode"
	"unicode/utf16"
)

// pyKeys orders a decoded object's keys: the keys the message parts are built
// with first, in the order Python inserts them, the rest sorted.
func pyKeys(m map[string]any) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	rank := func(k string) int {
		if i := slices.Index([]string{"type", "text", "image_url", "url"}, k); i >= 0 {
			return i
		}
		return 4
	}
	slices.SortFunc(keys, func(a, b string) int {
		if ra, rb := rank(a), rank(b); ra != rb {
			return ra - rb
		}
		return strings.Compare(a, b)
	})
	return keys
}

// pyRepr is Python's repr() of a json.loads value.
func pyRepr(v any) string {
	switch t := v.(type) {
	case nil:
		return "None"
	case bool:
		if t {
			return "True"
		}
		return "False"
	case string:
		return pyStrRepr(t)
	case json.Number:
		return PyNumberStr(t)
	case float64:
		return PyFloatRepr(t)
	case int:
		return fmt.Sprint(t)
	case []any:
		parts := make([]string, len(t))
		for i, x := range t {
			parts[i] = pyRepr(x)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case map[string]any:
		parts := make([]string, 0, len(t))
		for _, k := range pyKeys(t) {
			parts = append(parts, pyStrRepr(k)+": "+pyRepr(t[k]))
		}
		return "{" + strings.Join(parts, ", ") + "}"
	}
	return fmt.Sprint(v)
}

func pyStrRepr(s string) string {
	quote := byte('\'')
	if strings.ContainsRune(s, '\'') && !strings.ContainsRune(s, '"') {
		quote = '"'
	}
	var b strings.Builder
	b.WriteByte(quote)
	for _, r := range s {
		switch {
		case r == rune(quote) || r == '\\':
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
		case r < 0x80 || unicode.IsPrint(r):
			b.WriteRune(r)
		case r <= 0xff:
			fmt.Fprintf(&b, `\x%02x`, r)
		case r <= 0xffff:
			fmt.Fprintf(&b, `\u%04x`, r)
		default:
			fmt.Fprintf(&b, `\U%08x`, r)
		}
	}
	b.WriteByte(quote)
	return b.String()
}

// pyDumps is json.dumps with its defaults: ", " and ": " separators, ensure_ascii.
func pyDumps(b *strings.Builder, v any) error {
	switch t := v.(type) {
	case nil:
		b.WriteString("null")
	case bool:
		b.WriteString(map[bool]string{true: "true", false: "false"}[t])
	case string:
		pyDumpsString(b, t)
	case json.Number:
		b.WriteString(PyNumberStr(t))
	case float64:
		switch {
		case math.IsNaN(t):
			b.WriteString("NaN")
		case math.IsInf(t, 1):
			b.WriteString("Infinity")
		case math.IsInf(t, -1):
			b.WriteString("-Infinity")
		default:
			b.WriteString(PyFloatRepr(t))
		}
	case int:
		fmt.Fprint(b, t)
	case []any:
		b.WriteByte('[')
		for i, x := range t {
			if i > 0 {
				b.WriteString(", ")
			}
			if err := pyDumps(b, x); err != nil {
				return err
			}
		}
		b.WriteByte(']')
	case map[string]any:
		b.WriteByte('{')
		for i, k := range pyKeys(t) {
			if i > 0 {
				b.WriteString(", ")
			}
			pyDumpsString(b, k)
			b.WriteString(": ")
			if err := pyDumps(b, t[k]); err != nil {
				return err
			}
		}
		b.WriteByte('}')
	default:
		raw, err := json.Marshal(v)
		if err != nil {
			return err
		}
		var back any
		dec := json.NewDecoder(strings.NewReader(string(raw)))
		dec.UseNumber()
		if err := dec.Decode(&back); err != nil {
			return err
		}
		return pyDumps(b, back)
	}
	return nil
}

func pyDumpsString(b *strings.Builder, s string) {
	b.WriteByte('"')
	for _, r := range s {
		switch {
		case r == '"':
			b.WriteString(`\"`)
		case r == '\\':
			b.WriteString(`\\`)
		case r == '\n':
			b.WriteString(`\n`)
		case r == '\r':
			b.WriteString(`\r`)
		case r == '\t':
			b.WriteString(`\t`)
		case r == '\b':
			b.WriteString(`\b`)
		case r == '\f':
			b.WriteString(`\f`)
		case r >= 0x20 && r <= 0x7e:
			b.WriteRune(r)
		case r > 0xffff:
			r1, r2 := utf16.EncodeRune(r)
			fmt.Fprintf(b, `\u%04x\u%04x`, r1, r2)
		default:
			fmt.Fprintf(b, `\u%04x`, r)
		}
	}
	b.WriteByte('"')
}
