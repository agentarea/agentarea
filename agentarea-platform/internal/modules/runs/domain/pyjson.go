package domain

import (
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"unicode/utf16"
)

// KV is one key of an Ordered object.
type KV struct {
	Key   string
	Value any
}

// Ordered is a JSON object that keeps its key order, as a Python dict does.
type Ordered []KV

// MarshalJSON writes the keys in order.
func (o Ordered) MarshalJSON() ([]byte, error) {
	var b strings.Builder
	b.WriteByte('{')
	for i, kv := range o {
		if i > 0 {
			b.WriteByte(',')
		}
		k, _ := json.Marshal(kv.Key)
		v, err := json.Marshal(kv.Value)
		if err != nil {
			return nil, err
		}
		b.Write(k)
		b.WriteByte(':')
		b.Write(v)
	}
	b.WriteByte('}')
	return []byte(b.String()), nil
}

// PyDumps is Python's json.dumps(v): ", " and ": " separators and ASCII
// escapes. Compact is separators=(",", ":") with ensure_ascii=False.
func PyDumps(v any) string {
	var b strings.Builder
	pyEncode(&b, v, ", ", ": ", true)
	return b.String()
}

// PyDumpsCompact is json.dumps(v, ensure_ascii=False, separators=(",", ":")).
func PyDumpsCompact(v any) string {
	var b strings.Builder
	pyEncode(&b, v, ",", ":", false)
	return b.String()
}

func pyEncode(b *strings.Builder, v any, item, key string, ascii bool) {
	switch x := v.(type) {
	case nil:
		b.WriteString("null")
	case bool:
		if x {
			b.WriteString("true")
		} else {
			b.WriteString("false")
		}
	case string:
		pyString(b, x, ascii)
	case int:
		b.WriteString(strconv.Itoa(x))
	case int64:
		b.WriteString(strconv.FormatInt(x, 10))
	case float64:
		b.WriteString(PyFloat(x))
	case json.Number:
		b.WriteString(x.String())
	case Ordered:
		b.WriteByte('{')
		for i, kv := range x {
			if i > 0 {
				b.WriteString(item)
			}
			pyString(b, kv.Key, ascii)
			b.WriteString(key)
			pyEncode(b, kv.Value, item, key, ascii)
		}
		b.WriteByte('}')
	case map[string]any:
		keys := make([]string, 0, len(x))
		for k := range x {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		o := make(Ordered, len(keys))
		for i, k := range keys {
			o[i] = KV{k, x[k]}
		}
		pyEncode(b, o, item, key, ascii)
	case []string:
		b.WriteByte('[')
		for i, s := range x {
			if i > 0 {
				b.WriteString(item)
			}
			pyString(b, s, ascii)
		}
		b.WriteByte(']')
	case []any:
		b.WriteByte('[')
		for i, e := range x {
			if i > 0 {
				b.WriteString(item)
			}
			pyEncode(b, e, item, key, ascii)
		}
		b.WriteByte(']')
	default:
		raw, err := json.Marshal(x)
		if err != nil {
			b.WriteString(strconv.Quote(fmt.Sprint(x)))
			return
		}
		var generic any
		d := json.NewDecoder(strings.NewReader(string(raw)))
		d.UseNumber()
		if d.Decode(&generic) != nil {
			b.Write(raw)
			return
		}
		pyEncode(b, generic, item, key, ascii)
	}
}

func pyString(b *strings.Builder, s string, ascii bool) {
	b.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			b.WriteString(`\"`)
		case '\\':
			b.WriteString(`\\`)
		case '\n':
			b.WriteString(`\n`)
		case '\r':
			b.WriteString(`\r`)
		case '\t':
			b.WriteString(`\t`)
		case '\b':
			b.WriteString(`\b`)
		case '\f':
			b.WriteString(`\f`)
		default:
			switch {
			case r < 0x20:
				fmt.Fprintf(b, `\u%04x`, r)
			case r > 0x7e && ascii:
				if r > 0xffff {
					r1, r2 := utf16.EncodeRune(r)
					fmt.Fprintf(b, `\u%04x\u%04x`, r1, r2)
				} else {
					fmt.Fprintf(b, `\u%04x`, r)
				}
			default:
				b.WriteRune(r)
			}
		}
	}
	b.WriteByte('"')
}

// PyFloat is Python's repr of a float.
func PyFloat(f float64) string {
	switch {
	case math.IsInf(f, 1):
		return "Infinity"
	case math.IsInf(f, -1):
		return "-Infinity"
	case math.IsNaN(f):
		return "NaN"
	}
	s := strconv.FormatFloat(f, 'g', -1, 64)
	if mant, exp, found := strings.Cut(s, "e"); found {
		e, _ := strconv.Atoi(exp)
		if e >= -4 && e < 16 {
			s = strconv.FormatFloat(f, 'f', -1, 64)
		} else {
			sign := "+"
			if e < 0 {
				sign, e = "-", -e
			}
			return fmt.Sprintf("%se%s%02d", mant, sign, e)
		}
	}
	if abs := math.Abs(f); abs >= 1e16 {
		return strings.Replace(strconv.FormatFloat(f, 'e', -1, 64), "e+", "e+", 1)
	}
	if !strings.ContainsAny(s, ".e") {
		s += ".0"
	}
	return s
}

// PyDumpsCanonical is json.dumps(v, sort_keys=True, separators=(",", ":")): ASCII escapes, no
// whitespace.
func PyDumpsCanonical(v any) string {
	var b strings.Builder
	pyEncode(&b, v, ",", ":", true)
	return b.String()
}
