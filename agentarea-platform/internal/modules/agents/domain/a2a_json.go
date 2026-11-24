package domain

import (
	"encoding/json"
	"fmt"
	"math"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

// A2AJSON is a JSON object in key order: the order protobuf's MessageToDict
// writes a message in, or the order a decoded request carried. Values are
// string, bool, int, float64 (a Python float), json.Number (a request's
// integer), nil, A2AJSON, []any and []string.
type A2AJSON []A2AMember

// A2AMember is one key of an A2AJSON.
type A2AMember struct {
	Key   string
	Value any
}

// Get is the value of key.
func (o A2AJSON) Get(key string) (any, bool) {
	for _, m := range o {
		if m.Key == key {
			return m.Value, true
		}
	}
	return nil, false
}

// Set is a dict assignment: a key already there keeps its place.
func (o *A2AJSON) Set(key string, v any) {
	for i := range *o {
		if (*o)[i].Key == key {
			(*o)[i].Value = v
			return
		}
	}
	*o = append(*o, A2AMember{Key: key, Value: v})
}

// Delete is dict.pop(key, None).
func (o *A2AJSON) Delete(key string) {
	for i := range *o {
		if (*o)[i].Key == key {
			*o = append((*o)[:i], (*o)[i+1:]...)
			return
		}
	}
}

func a2aString(o A2AJSON, key string) (string, bool) {
	v, _ := o.Get(key)
	s, ok := v.(string)
	return s, ok
}

// a2aTruthy is Python's bool(v) for a decoded JSON value.
func a2aTruthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case string:
		return x != ""
	case int:
		return x != 0
	case float64:
		return x != 0
	case json.Number:
		f, err := x.Float64()
		return err != nil || f != 0
	case A2AJSON:
		return len(x) > 0
	case []any:
		return len(x) > 0
	}
	return true
}

// a2aPyType is type(v).__name__ for a decoded JSON value.
func a2aPyType(v any) string {
	switch x := v.(type) {
	case nil:
		return "NoneType"
	case bool:
		return "bool"
	case string:
		return "str"
	case int:
		return "int"
	case float64:
		return "float"
	case json.Number:
		if a2aIsFloatLiteral(x) {
			return "float"
		}
		return "int"
	case A2AJSON:
		return "dict"
	case []any:
		return "list"
	}
	return fmt.Sprintf("%T", v)
}

func a2aIsFloatLiteral(n json.Number) bool { return strings.ContainsAny(string(n), ".eE") }

// a2aPyStr is Python's str(v) for a decoded JSON value.
func a2aPyStr(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return a2aPyRepr(v)
}

// a2aPyRepr is Python's repr(v) for a decoded JSON value.
func a2aPyRepr(v any) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case bool:
		if x {
			return "True"
		}
		return "False"
	case string:
		return a2aPyQuote(x)
	case int:
		return strconv.Itoa(x)
	case float64:
		return a2aPyFloat(x)
	case json.Number:
		if a2aIsFloatLiteral(x) {
			f, _ := x.Float64()
			return a2aPyFloat(f)
		}
		return string(x)
	case A2AJSON:
		parts := make([]string, len(x))
		for i, m := range x {
			parts[i] = a2aPyQuote(m.Key) + ": " + a2aPyRepr(m.Value)
		}
		return "{" + strings.Join(parts, ", ") + "}"
	case []any:
		parts := make([]string, len(x))
		for i, e := range x {
			parts[i] = a2aPyRepr(e)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	}
	return fmt.Sprint(v)
}

// a2aPyFloat is repr(float).
func a2aPyFloat(v float64) string {
	switch {
	case math.IsNaN(v):
		return "nan"
	case math.IsInf(v, 1):
		return "inf"
	case math.IsInf(v, -1):
		return "-inf"
	case v == 0:
		if math.Signbit(v) {
			return "-0.0"
		}
		return "0.0"
	}
	sci := strconv.FormatFloat(v, 'e', -1, 64)
	sign := ""
	if strings.HasPrefix(sci, "-") {
		sign, sci = "-", sci[1:]
	}
	mant, expPart, _ := strings.Cut(sci, "e")
	exp, _ := strconv.Atoi(expPart)
	digits := strings.Replace(mant, ".", "", 1)
	if exp < -4 || exp >= 16 {
		m := digits[:1]
		if len(digits) > 1 {
			m += "." + digits[1:]
		}
		return sign + m + fmt.Sprintf("e%+03d", exp)
	}
	decpt := exp + 1
	switch {
	case decpt <= 0:
		return sign + "0." + strings.Repeat("0", -decpt) + digits
	case decpt >= len(digits):
		return sign + digits + strings.Repeat("0", decpt-len(digits)) + ".0"
	}
	return sign + digits[:decpt] + "." + digits[decpt:]
}

// a2aPyQuote is repr(str): single quotes unless the text holds one and no double quote.
func a2aPyQuote(s string) string {
	q := byte('\'')
	if strings.Contains(s, "'") && !strings.Contains(s, `"`) {
		q = '"'
	}
	var b strings.Builder
	b.WriteByte(q)
	for _, r := range s {
		switch {
		case r == rune(q) || r == '\\':
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
		case !unicode.IsPrint(r) && r != ' ':
			switch {
			case r <= 0xff:
				fmt.Fprintf(&b, `\x%02x`, r)
			case r <= 0xffff:
				fmt.Fprintf(&b, `\u%04x`, r)
			default:
				fmt.Fprintf(&b, `\U%08x`, r)
			}
		default:
			b.WriteRune(r)
		}
	}
	b.WriteByte(q)
	return b.String()
}

func a2aPySpace(r rune) bool { return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f) }

// a2aPyStrip is str.strip().
func a2aPyStrip(s string) string { return strings.TrimFunc(s, a2aPySpace) }

// a2aSplitLines is str.splitlines().
func a2aSplitLines(s string) []string {
	var out []string
	start := 0
	for i := 0; i < len(s); {
		r, size := utf8.DecodeRuneInString(s[i:])
		switch r {
		case '\n', '\r', '\v', '\f', 0x1c, 0x1d, 0x1e, 0x85, 0x2028, 0x2029:
			out = append(out, s[start:i])
			i += size
			if r == '\r' && i < len(s) && s[i] == '\n' {
				i++
			}
			start = i
			continue
		}
		i += size
	}
	if start < len(s) {
		out = append(out, s[start:])
	}
	return out
}

// a2aPrefixRunes is s[:n] over code points.
func a2aPrefixRunes(s string, n int) string {
	i := 0
	for pos := range s {
		if i == n {
			return s[:pos]
		}
		i++
	}
	return s
}
