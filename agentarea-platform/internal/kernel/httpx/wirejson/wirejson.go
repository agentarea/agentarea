// Package wirejson writes the JSON bytes clients and log readers already
// receive from the API and reads JSON keeping key order and the int/float
// distinction. The HTTP contract is FastAPI's output: problem bodies, SSE
// frames and log lines must not change at cutover, and encoding/json writes
// none of them byte for byte.
//
// Two dialects reach the wire. Starlette's JSONResponse (every problem body)
// calls json.dumps(ensure_ascii=False, separators=(",", ":")); the SSE frames
// and the JSON log lines call json.dumps with its defaults (ASCII escapes,
// ", " and ": "). encoding/json differs from both: it escapes <, > and &,
// writes U+2028/U+2029 escaped, and renders 10.0 as 10.
package wirejson

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"strconv"
	"strings"
	"unicode/utf8"
)

// Style is a json.dumps configuration.
type Style int

const (
	// Compact is json.dumps(ensure_ascii=False, separators=(",", ":")),
	// Starlette's JSONResponse.
	Compact Style = iota
	// Dumps is json.dumps with its defaults: ensure_ascii=True, ", " and ": ".
	Dumps
)

// Member is one key of an Object.
type Member struct {
	Key   string
	Value any
}

// Object is a JSON object in insertion order, as a Python dict is.
type Object []Member

// Get returns the value under key.
func (o Object) Get(key string) (any, bool) {
	for _, m := range o {
		if m.Key == key {
			return m.Value, true
		}
	}
	return nil, false
}

// Set replaces the value under key in place, or appends it (d[key] = v).
func (o *Object) Set(key string, v any) {
	for i := range *o {
		if (*o)[i].Key == key {
			(*o)[i].Value = v
			return
		}
	}
	*o = append(*o, Member{Key: key, Value: v})
}

// SetDefault appends key unless it is present (dict.setdefault).
func (o *Object) SetDefault(key string, v any) {
	if _, ok := o.Get(key); !ok {
		*o = append(*o, Member{Key: key, Value: v})
	}
}

// MarshalJSON writes the members in order.
func (o Object) MarshalJSON() ([]byte, error) {
	var buf bytes.Buffer
	buf.WriteByte('{')
	for i, m := range o {
		if i > 0 {
			buf.WriteByte(',')
		}
		k, err := json.Marshal(m.Key)
		if err != nil {
			return nil, err
		}
		buf.Write(k)
		buf.WriteByte(':')
		v, err := marshalGo(m.Value)
		if err != nil {
			return nil, fmt.Errorf("key %q: %w", m.Key, err)
		}
		buf.Write(v)
	}
	buf.WriteByte('}')
	return buf.Bytes(), nil
}

// Float is a Python float: it is written as Python's repr writes it, so 10.0
// stays 10.0 and 1e16 is 1e+16.
type Float float64

// ErrNotFinite is NaN or an infinity, which Starlette refuses to render.
var ErrNotFinite = errors.New("out of range float values are not JSON compliant")

// MarshalJSON writes Python's repr of f.
func (f Float) MarshalJSON() ([]byte, error) {
	v := float64(f)
	if math.IsNaN(v) || math.IsInf(v, 0) {
		return nil, ErrNotFinite
	}
	return []byte(FormatFloat(v)), nil
}

// FormatFloat is Python's repr(float): the shortest digits that round-trip,
// in positional notation while the decimal exponent is in [-4, 16), with ".0"
// on an integral value; otherwise d.ddde±XX.
func FormatFloat(v float64) string {
	if v == 0 {
		if math.Signbit(v) {
			return "-0.0"
		}
		return "0.0"
	}
	sci := strconv.FormatFloat(v, 'e', -1, 64)
	neg := strings.HasPrefix(sci, "-")
	sci = strings.TrimPrefix(sci, "-")
	mant, expPart, _ := strings.Cut(sci, "e")
	exp, _ := strconv.Atoi(expPart)
	digits := strings.Replace(mant, ".", "", 1)
	decpt := exp + 1
	var out strings.Builder
	if neg {
		out.WriteByte('-')
	}
	switch {
	case decpt <= -4 || decpt > 16:
		out.WriteByte(digits[0])
		if len(digits) > 1 {
			out.WriteByte('.')
			out.WriteString(digits[1:])
		}
		out.WriteByte('e')
		if exp < 0 {
			out.WriteByte('-')
			exp = -exp
		} else {
			out.WriteByte('+')
		}
		if exp < 10 {
			out.WriteByte('0')
		}
		out.WriteString(strconv.Itoa(exp))
	case decpt <= 0:
		out.WriteString("0.")
		out.WriteString(strings.Repeat("0", -decpt))
		out.WriteString(digits)
	case decpt >= len(digits):
		out.WriteString(digits)
		out.WriteString(strings.Repeat("0", decpt-len(digits)))
		out.WriteString(".0")
	default:
		out.WriteString(digits[:decpt])
		out.WriteByte('.')
		out.WriteString(digits[decpt:])
	}
	return out.String()
}

func marshalGo(v any) ([]byte, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return nil, err
	}
	return bytes.TrimSuffix(buf.Bytes(), []byte("\n")), nil
}

// Marshal renders v as Python's json.dumps would in style s. v is anything
// encoding/json accepts; use Object for key order and Float for a float.
func Marshal(v any, s Style) ([]byte, error) {
	raw, err := marshalGo(v)
	if err != nil {
		return nil, err
	}
	return Restyle(raw, s)
}

// Restyle rewrites compact JSON (encoding/json's output) into style s:
// separators and string escapes; number literals are kept as they are.
func Restyle(raw []byte, s Style) ([]byte, error) {
	out := make([]byte, 0, len(raw)+len(raw)/8)
	for i := 0; i < len(raw); i++ {
		c := raw[i]
		switch c {
		case '"':
			end, err := stringEnd(raw, i)
			if err != nil {
				return nil, err
			}
			var str string
			if err := json.Unmarshal(raw[i:end], &str); err != nil {
				return nil, err
			}
			out = AppendString(out, str, s)
			i = end - 1
		case ',':
			if s == Dumps {
				out = append(out, ',', ' ')
			} else {
				out = append(out, ',')
			}
		case ':':
			if s == Dumps {
				out = append(out, ':', ' ')
			} else {
				out = append(out, ':')
			}
		case ' ', '\t', '\n', '\r':
		default:
			out = append(out, c)
		}
	}
	return out, nil
}

func stringEnd(raw []byte, start int) (int, error) {
	for j := start + 1; j < len(raw); j++ {
		switch raw[j] {
		case '\\':
			j++
		case '"':
			return j + 1, nil
		}
	}
	return 0, errors.New("wirejson: unterminated string")
}

const hexDigits = "0123456789abcdef"

// AppendString appends str quoted as Python's json encoder quotes it.
// Invalid UTF-8 becomes U+FFFD, as encoding/json does.
func AppendString(dst []byte, str string, s Style) []byte {
	dst = append(dst, '"')
	for _, r := range str {
		switch r {
		case '"':
			dst = append(dst, '\\', '"')
		case '\\':
			dst = append(dst, '\\', '\\')
		case '\n':
			dst = append(dst, '\\', 'n')
		case '\r':
			dst = append(dst, '\\', 'r')
		case '\t':
			dst = append(dst, '\\', 't')
		case '\b':
			dst = append(dst, '\\', 'b')
		case '\f':
			dst = append(dst, '\\', 'f')
		default:
			switch {
			case r < 0x20:
				dst = appendU(dst, r)
			case s == Dumps && r > 0x7e:
				if r > 0xffff {
					r -= 0x10000
					dst = appendU(dst, 0xd800+(r>>10))
					dst = appendU(dst, 0xdc00+(r&0x3ff))
				} else {
					dst = appendU(dst, r)
				}
			default:
				dst = utf8.AppendRune(dst, r)
			}
		}
	}
	return append(dst, '"')
}

func appendU(dst []byte, r rune) []byte {
	return append(dst, '\\', 'u', hexDigits[r>>12&0xf], hexDigits[r>>8&0xf], hexDigits[r>>4&0xf], hexDigits[r&0xf])
}

// Unmarshal reads JSON keeping Python's view of it: objects as Object in
// key order (a repeated key keeps its first position and last value),
// numbers with a fraction or exponent as Float, other numbers as
// json.Number, strings, bools, nil and []any.
func Unmarshal(data []byte) (any, error) {
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	v, err := decodeValue(dec)
	if err != nil {
		return nil, err
	}
	if dec.More() {
		return nil, errors.New("wirejson: extra data after the value")
	}
	return v, nil
}

func decodeValue(dec *json.Decoder) (any, error) {
	tok, err := dec.Token()
	if err != nil {
		return nil, err
	}
	switch t := tok.(type) {
	case json.Delim:
		switch t {
		case '{':
			obj := Object{}
			for dec.More() {
				kt, err := dec.Token()
				if err != nil {
					return nil, err
				}
				key, _ := kt.(string)
				v, err := decodeValue(dec)
				if err != nil {
					return nil, err
				}
				obj.Set(key, v)
			}
			_, err := dec.Token()
			return obj, err
		case '[':
			arr := []any{}
			for dec.More() {
				v, err := decodeValue(dec)
				if err != nil {
					return nil, err
				}
				arr = append(arr, v)
			}
			_, err := dec.Token()
			return arr, err
		}
		return nil, fmt.Errorf("wirejson: unexpected %v", t)
	case json.Number:
		if strings.ContainsAny(string(t), ".eE") {
			f, err := t.Float64()
			return Float(f), err
		}
		return t, nil
	default:
		return t, nil
	}
}
