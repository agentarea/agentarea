package domain

import (
	"encoding/json"
	"math"
	"regexp"
	"strconv"
	"strings"
)

// Template is one template, or several of which the first that renders is the value; nil is none.
type Template []string

// UnmarshalJSON reads str | list[str].
func (t *Template) UnmarshalJSON(b []byte) error {
	var one string
	if err := json.Unmarshal(b, &one); err == nil {
		*t = Template{one}
		return nil
	}
	var many []string
	if err := json.Unmarshal(b, &many); err != nil {
		return &ValidationError{Msg: "a template is a string or a list of strings"}
	}
	if many == nil {
		*t = nil
		return nil
	}
	*t = Template(many)
	return nil
}

// MarshalJSON writes one template as a string and several as a list.
func (t Template) MarshalJSON() ([]byte, error) {
	if t == nil {
		return []byte("null"), nil
	}
	if len(t) == 1 {
		return json.Marshal(t[0])
	}
	return json.Marshal([]string(t))
}

// TemplateContext is what a template may read: an event's body and headers, and named values.
type TemplateContext struct {
	Body    any
	Headers map[string]string
	Values  map[string]any
}

// Header is the header named name, case-insensitive.
func (c TemplateContext) Header(name string) (string, bool) {
	want := strings.ToLower(name)
	for k, v := range c.Headers {
		if strings.ToLower(k) == want {
			return v, true
		}
	}
	return "", false
}

var placeholderRE = regexp.MustCompile(`\{([^{}]+)\}`)

// PathValue is the value at a dotted path (a number indexes a list), nil when any step is missing.
func PathValue(data any, path string) any {
	if path == "" {
		return nil
	}
	cur := data
	for _, step := range strings.Split(path, ".") {
		switch v := cur.(type) {
		case map[string]any:
			next, ok := v[step]
			if !ok {
				return nil
			}
			cur = next
		case []any:
			i, err := strconv.Atoi(step)
			if err != nil || !isDigits(step) || i >= len(v) {
				return nil
			}
			cur = v[i]
		default:
			return nil
		}
	}
	return cur
}

func isDigits(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

func absent(v any) bool {
	if v == nil {
		return true
	}
	s, ok := v.(string)
	return ok && s == ""
}

func firstPath(data any, paths string) any {
	for _, p := range strings.Split(paths, "|") {
		if v := PathValue(data, strings.TrimSpace(p)); !absent(v) {
			return v
		}
	}
	return nil
}

// PlaceholderValue is one placeholder's value, nil when it has none. A malformed placeholder
// (an unknown kind) has none.
func PlaceholderValue(expr string, c TemplateContext) any {
	if kind, arg, ok := strings.Cut(expr, ":"); ok {
		kind = strings.TrimSpace(kind)
		switch kind {
		case "body":
			return firstPath(c.Body, arg)
		case "header":
			if v, ok := c.Header(strings.TrimSpace(arg)); ok {
				return v
			}
			return nil
		case "first_key":
			m, ok := c.Body.(map[string]any)
			if !ok {
				return nil
			}
			for _, k := range strings.Split(arg, "|") {
				if _, has := m[strings.TrimSpace(k)]; has {
					return strings.TrimSpace(k)
				}
			}
			return nil
		}
		if scope, ok := c.Values[kind]; ok {
			if m, isMap := scope.(map[string]any); isMap {
				return PathValue(m, strings.TrimSpace(arg))
			}
			if m, isMap := scope.(map[string]string); isMap {
				return PathValue(stringMap(m), strings.TrimSpace(arg))
			}
		}
		return nil
	}
	name := strings.TrimSpace(expr)
	if v, ok := c.Values[name]; ok {
		return v
	}
	if scope, rest, ok := strings.Cut(name, "."); ok {
		switch m := c.Values[scope].(type) {
		case map[string]any:
			return PathValue(m, rest)
		case map[string]string:
			return PathValue(stringMap(m), rest)
		}
	}
	return nil
}

func stringMap(m map[string]string) map[string]any {
	out := make(map[string]any, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}

// Render fills tpl in; false when any placeholder has no value.
func Render(tpl string, c TemplateContext) (string, bool) {
	return render(tpl, c, nil)
}

// RenderURL fills tpl in with each value percent-encoded, so it fills one segment.
func RenderURL(tpl string, c TemplateContext) (string, bool) {
	return render(tpl, c, quoteAll)
}

func render(tpl string, c TemplateContext, encode func(string) string) (string, bool) {
	var b strings.Builder
	pos := 0
	for _, m := range placeholderRE.FindAllStringSubmatchIndex(tpl, -1) {
		b.WriteString(tpl[pos:m[0]])
		v := PlaceholderValue(tpl[m[2]:m[3]], c)
		if absent(v) {
			return "", false
		}
		text, ok := Scalar(v)
		if !ok {
			return "", false
		}
		if encode != nil {
			text = encode(text)
		}
		b.WriteString(text)
		pos = m[1]
	}
	b.WriteString(tpl[pos:])
	return b.String(), true
}

// RenderFirst is the first of t that renders.
func RenderFirst(t Template, c TemplateContext) (string, bool) {
	for _, tpl := range t {
		if v, ok := Render(tpl, c); ok {
			return v, true
		}
	}
	return "", false
}

// RenderValue is a JSON value with every string leaf rendered: a leaf that is one placeholder
// keeps its value's type, a leaf that cannot render is left out of its object, and an object
// left with nothing is left out of its parent (nil).
func RenderValue(tpl any, c TemplateContext) any {
	switch v := tpl.(type) {
	case string:
		if m := placeholderRE.FindStringSubmatchIndex(v); m != nil && m[0] == 0 && m[1] == len(v) {
			return PlaceholderValue(v[m[2]:m[3]], c)
		}
		if s, ok := Render(v, c); ok {
			return s
		}
		return nil
	case map[string]any:
		kept := make(map[string]any, len(v))
		for k, item := range v {
			if r := RenderValue(item, c); r != nil {
				kept[k] = r
			}
		}
		if len(kept) == 0 && len(v) > 0 {
			return nil
		}
		return kept
	case map[string]string:
		m := stringMap(v)
		return RenderValue(m, c)
	case []any:
		out := make([]any, len(v))
		for i, item := range v {
			out[i] = RenderValue(item, c)
		}
		return out
	}
	return tpl
}

// Scalar is a placeholder value as text: a string as is, a bool as true/false, a number as
// Python prints it; false for an object or a list.
func Scalar(v any) (string, bool) {
	switch x := v.(type) {
	case string:
		return x, true
	case bool:
		if x {
			return "true", true
		}
		return "false", true
	case json.Number:
		return pyNumber(string(x)), true
	case float64:
		return PyFloat(x), true
	case int:
		return strconv.Itoa(x), true
	case int64:
		return strconv.FormatInt(x, 10), true
	}
	return "", false
}

func pyNumber(s string) string {
	if !strings.ContainsAny(s, ".eE") {
		if n, ok := strings.CutPrefix(s, "-"); ok && strings.Trim(n, "0") == "" {
			return "0"
		}
		return s
	}
	f, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return s
	}
	return PyFloat(f)
}

// PyFloat is repr(float).
func PyFloat(f float64) string {
	switch {
	case math.IsInf(f, 1):
		return "inf"
	case math.IsInf(f, -1):
		return "-inf"
	case math.IsNaN(f):
		return "nan"
	}
	e := strconv.FormatFloat(f, 'e', -1, 64)
	mant, expPart, _ := strings.Cut(e, "e")
	exp, _ := strconv.Atoi(expPart)
	if exp < -4 || exp >= 16 {
		sign := "+"
		if exp < 0 {
			sign = "-"
			exp = -exp
		}
		es := strconv.Itoa(exp)
		if len(es) < 2 {
			es = "0" + es
		}
		return mant + "e" + sign + es
	}
	s := strconv.FormatFloat(f, 'f', -1, 64)
	if !strings.Contains(s, ".") {
		s += ".0"
	}
	return s
}

// quoteAll is urllib.parse.quote(text, safe=""): every byte but A-Z a-z 0-9 _ . - ~ escaped.
func quoteAll(s string) string {
	const hex = "0123456789ABCDEF"
	var b strings.Builder
	for i := 0; i < len(s); i++ {
		c := s[i]
		if c >= 'A' && c <= 'Z' || c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '_' || c == '.' || c == '-' || c == '~' {
			b.WriteByte(c)
			continue
		}
		b.WriteByte('%')
		b.WriteByte(hex[c>>4])
		b.WriteByte(hex[c&15])
	}
	return b.String()
}
