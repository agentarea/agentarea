package payment

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"math/big"
	"sort"
	"strconv"
	"strings"
	"unicode/utf16"
)

// The challenge formats the SDKs answer are re-serialized by Python's json
// module; these helpers read and write JSON the way json.loads / json.dumps do.

// decodeJSON is json.loads: one value, numbers kept as written.
func decodeJSON(data []byte) (any, error) {
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	if _, err := dec.Token(); !errors.Is(err, io.EOF) {
		return nil, errors.New("extra data after the JSON value")
	}
	return v, nil
}

// pyNumberText is how json.dumps writes a number json.loads read: ints
// exactly, floats as repr(float).
func pyNumberText(n json.Number) string {
	text := string(n)
	if !strings.ContainsAny(text, ".eE") {
		if i, ok := new(big.Int).SetString(text, 10); ok {
			return i.String()
		}
		return text
	}
	f, err := strconv.ParseFloat(text, 64)
	if err != nil {
		return text
	}
	return pyFloatRepr(f)
}

func pyFloatRepr(f float64) string {
	switch {
	case math.IsInf(f, 1):
		return "Infinity"
	case math.IsInf(f, -1):
		return "-Infinity"
	case math.IsNaN(f):
		return "NaN"
	}
	sci := strconv.FormatFloat(f, 'e', -1, 64)
	exp, _ := strconv.Atoi(sci[strings.IndexByte(sci, 'e')+1:])
	if exp < -4 || exp >= 16 {
		return sci
	}
	fixed := strconv.FormatFloat(f, 'f', -1, 64)
	if !strings.Contains(fixed, ".") {
		fixed += ".0"
	}
	return fixed
}

// pyDumps is json.dumps(v, separators=(",", ":"), sort_keys=True,
// ensure_ascii=ensureASCII).
func pyDumps(v any, ensureASCII bool) (string, error) {
	var b strings.Builder
	if err := pyDump(&b, v, ensureASCII); err != nil {
		return "", err
	}
	return b.String(), nil
}

func pyDump(b *strings.Builder, v any, ascii bool) error {
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
		pyQuote(b, x, ascii)
	case json.Number:
		b.WriteString(pyNumberText(x))
	case int:
		b.WriteString(strconv.Itoa(x))
	case int64:
		b.WriteString(strconv.FormatInt(x, 10))
	case map[string]any:
		keys := make([]string, 0, len(x))
		for k := range x {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		b.WriteByte('{')
		for i, k := range keys {
			if i > 0 {
				b.WriteByte(',')
			}
			pyQuote(b, k, ascii)
			b.WriteByte(':')
			if err := pyDump(b, x[k], ascii); err != nil {
				return err
			}
		}
		b.WriteByte('}')
	case []any:
		b.WriteByte('[')
		for i, it := range x {
			if i > 0 {
				b.WriteByte(',')
			}
			if err := pyDump(b, it, ascii); err != nil {
				return err
			}
		}
		b.WriteByte(']')
	default:
		return fmt.Errorf("json: cannot write %T", v)
	}
	return nil
}

func pyQuote(b *strings.Builder, s string, ascii bool) {
	const hexDigits = "0123456789abcdef"
	writeU := func(r rune) {
		b.WriteString(`\u`)
		for shift := 12; shift >= 0; shift -= 4 {
			b.WriteByte(hexDigits[(r>>uint(shift))&0xf])
		}
	}
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
				writeU(r)
			case ascii && r > 0x7e:
				if r > 0xffff {
					hi, lo := utf16.EncodeRune(r)
					writeU(hi)
					writeU(lo)
				} else {
					writeU(r)
				}
			default:
				b.WriteRune(r)
			}
		}
	}
	b.WriteByte('"')
}

// pyTruthy is Python's bool() of a json.loads value.
func pyTruthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case string:
		return x != ""
	case json.Number:
		f, err := strconv.ParseFloat(string(x), 64)
		return err != nil || f != 0
	case map[string]any:
		return len(x) > 0
	case []any:
		return len(x) > 0
	}
	return true
}

// pyStr is Python's str() of a json.loads scalar.
func pyStr(v any) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case bool:
		if x {
			return "True"
		}
		return "False"
	case string:
		return x
	case json.Number:
		return pyNumberText(x)
	}
	out, err := pyDumps(v, false)
	if err != nil {
		return fmt.Sprint(v)
	}
	return out
}

// pyIntText is Python's int() of a str: optional sign, decimal digits,
// surrounding whitespace, single underscores between digits.
func pyIntText(s string) (*big.Int, bool) {
	s = strings.TrimSpace(s)
	sign := ""
	if s != "" && (s[0] == '+' || s[0] == '-') {
		sign, s = s[:1], s[1:]
	}
	if s == "" || s[0] == '_' || s[len(s)-1] == '_' || strings.Contains(s, "__") {
		return nil, false
	}
	digits := strings.ReplaceAll(s, "_", "")
	for _, c := range digits {
		if c < '0' || c > '9' {
			return nil, false
		}
	}
	n, ok := new(big.Int).SetString(sign+digits, 10)
	return n, ok
}

// pyInt is Python's int() of a json.loads value: strings as pyIntText, ints
// as they are, floats truncated, bools as 0/1.
func pyInt(v any) (*big.Int, bool) {
	switch x := v.(type) {
	case bool:
		if x {
			return big.NewInt(1), true
		}
		return big.NewInt(0), true
	case string:
		return pyIntText(x)
	case json.Number:
		text := string(x)
		if !strings.ContainsAny(text, ".eE") {
			return new(big.Int).SetString(text, 10)
		}
		f, err := strconv.ParseFloat(text, 64)
		if err != nil || math.IsInf(f, 0) || math.IsNaN(f) {
			return nil, false
		}
		n, _ := new(big.Float).SetFloat64(math.Trunc(f)).Int(nil)
		return n, true
	}
	return nil, false
}

// orderedObject is a JSON object that keeps its keys in the order read, as a
// Python dict does; a repeated key keeps its first place and its last value.
type orderedObject []objectMember

type objectMember struct {
	Key   string
	Value json.RawMessage
}

func parseOrderedObject(raw []byte) (orderedObject, error) {
	dec := json.NewDecoder(bytes.NewReader(raw))
	tok, err := dec.Token()
	if err != nil {
		return nil, err
	}
	if d, ok := tok.(json.Delim); !ok || d != '{' {
		return nil, errors.New("not a JSON object")
	}
	var obj orderedObject
	for dec.More() {
		keyTok, err := dec.Token()
		if err != nil {
			return nil, err
		}
		key, _ := keyTok.(string)
		var value json.RawMessage
		if err := dec.Decode(&value); err != nil {
			return nil, err
		}
		obj = obj.with(key, value)
	}
	if _, err := dec.Token(); err != nil {
		return nil, err
	}
	if _, err := dec.Token(); !errors.Is(err, io.EOF) {
		return nil, errors.New("extra data after the JSON object")
	}
	return obj, nil
}

func (o orderedObject) get(key string) (json.RawMessage, bool) {
	for _, m := range o {
		if m.Key == key {
			return m.Value, true
		}
	}
	return nil, false
}

// with returns o with key set, in place when present, appended when not.
func (o orderedObject) with(key string, value json.RawMessage) orderedObject {
	out := make(orderedObject, len(o), len(o)+1)
	copy(out, o)
	for i := range out {
		if out[i].Key == key {
			out[i].Value = value
			return out
		}
	}
	return append(out, objectMember{Key: key, Value: value})
}

func (o orderedObject) MarshalJSON() ([]byte, error) {
	var buf bytes.Buffer
	buf.WriteByte('{')
	for i, m := range o {
		if i > 0 {
			buf.WriteByte(',')
		}
		key, err := marshalNoEscape(m.Key)
		if err != nil {
			return nil, err
		}
		buf.Write(key)
		buf.WriteByte(':')
		if err := json.Compact(&buf, m.Value); err != nil {
			return nil, err
		}
	}
	buf.WriteByte('}')
	return buf.Bytes(), nil
}

// marshalNoEscape is json.Marshal without the HTML escaping pydantic does
// not do.
func marshalNoEscape(v any) ([]byte, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return nil, err
	}
	return bytes.TrimRight(buf.Bytes(), "\n"), nil
}

func isJSONNull(raw json.RawMessage) bool {
	return len(raw) == 0 || string(bytes.TrimSpace(raw)) == "null"
}
