// Package template renders the catalog's substitution templates (ADR-0040 §2):
// literal text joined with placeholders, nothing computed. A placeholder with no
// value is an error: a request template that cannot be filled is not sent.
package template

import (
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

// ErrMissing is wrapped by every error about a placeholder with no value.
var ErrMissing = errors.New("template value missing")

// Values are what request templates may name.
type Values struct {
	Credentials map[string]string
	Config      map[string]any
	// Cursor is the source's poll position; "" before the first poll.
	Cursor     string
	WebhookURL string
	SourceID   string
	Item       any
}

func (v Values) resolve(expr string) (any, error) {
	switch {
	case strings.HasPrefix(expr, "credentials."):
		key := strings.TrimPrefix(expr, "credentials.")
		value, ok := v.Credentials[key]
		if !ok || value == "" {
			return nil, fmt.Errorf("{%s}: %w", expr, ErrMissing)
		}
		return value, nil
	case strings.HasPrefix(expr, "config."):
		key := strings.TrimPrefix(expr, "config.")
		value, ok := v.Config[key]
		if !ok || value == nil || value == "" {
			return nil, fmt.Errorf("{%s}: %w", expr, ErrMissing)
		}
		return value, nil
	case expr == "cursor":
		return v.Cursor, nil
	case expr == "webhook_url":
		if v.WebhookURL == "" {
			return nil, fmt.Errorf("{%s}: %w", expr, ErrMissing)
		}
		return v.WebhookURL, nil
	case expr == "source_id":
		if v.SourceID == "" {
			return nil, fmt.Errorf("{%s}: %w", expr, ErrMissing)
		}
		return v.SourceID, nil
	case strings.HasPrefix(expr, "item:"):
		value, ok := Lookup(v.Item, strings.TrimPrefix(expr, "item:"))
		if !ok {
			return nil, fmt.Errorf("{%s}: %w", expr, ErrMissing)
		}
		return value, nil
	}
	return nil, fmt.Errorf("unknown placeholder {%s}", expr)
}

var placeholder = regexp.MustCompile(`\{([^{}]+)\}`)

// Render fills every placeholder of tmpl.
func Render(tmpl string, v Values) (string, error) {
	var firstErr error
	out := placeholder.ReplaceAllStringFunc(tmpl, func(match string) string {
		value, err := v.resolve(match[1 : len(match)-1])
		if err != nil {
			if firstErr == nil {
				firstErr = err
			}
			return ""
		}
		return Text(value)
	})
	if firstErr != nil {
		return "", firstErr
	}
	return out, nil
}

// RenderJSON renders every string leaf of a JSON body. A leaf that is exactly
// one placeholder keeps the type of its value; an object member whose value
// is missing is left out, as the platform's templates do.
func RenderJSON(body any, v Values) (any, error) {
	switch node := body.(type) {
	case string:
		if m := placeholder.FindStringSubmatchIndex(node); m != nil && m[0] == 0 && m[1] == len(node) {
			return v.resolve(node[1 : len(node)-1])
		}
		return Render(node, v)
	case map[string]any:
		out := make(map[string]any, len(node))
		for key, child := range node {
			rendered, err := RenderJSON(child, v)
			if errors.Is(err, ErrMissing) {
				continue
			}
			if err != nil {
				return nil, err
			}
			out[key] = rendered
		}
		return out, nil
	case []any:
		out := make([]any, len(node))
		for i, child := range node {
			rendered, err := RenderJSON(child, v)
			if err != nil {
				return nil, err
			}
			out[i] = rendered
		}
		return out, nil
	default:
		return body, nil
	}
}

var increment = regexp.MustCompile(`^(.*)\+(\d+)$`)

// RenderCursor renders a cursor template against the last item. A trailing
// "+N" adds N to the rendered integer: the one computation the catalog allows.
func RenderCursor(tmpl string, item any) (string, error) {
	base, step := tmpl, int64(0)
	if m := increment.FindStringSubmatch(tmpl); m != nil {
		n, err := strconv.ParseInt(m[2], 10, 64)
		if err != nil {
			return "", fmt.Errorf("cursor increment %q: %w", m[2], err)
		}
		base, step = m[1], n
	}
	rendered, err := Render(base, Values{Item: item})
	if err != nil {
		return "", err
	}
	if step == 0 {
		return rendered, nil
	}
	n, err := strconv.ParseInt(rendered, 10, 64)
	if err != nil {
		return "", fmt.Errorf("cursor %q is not an integer to add %d to: %w", rendered, step, err)
	}
	return strconv.FormatInt(n+step, 10), nil
}

// Lookup reads a dotted path ("a.b.0.c") from decoded JSON; "a.b|c.d" tries
// each path in turn and returns the first one present.
func Lookup(root any, path string) (any, bool) {
	for _, alternative := range strings.Split(path, "|") {
		if value, ok := lookupOne(root, strings.TrimSpace(alternative)); ok {
			return value, true
		}
	}
	return nil, false
}

func lookupOne(root any, path string) (any, bool) {
	if path == "" {
		return root, root != nil
	}
	current := root
	for _, part := range strings.Split(path, ".") {
		switch node := current.(type) {
		case map[string]any:
			next, ok := node[part]
			if !ok {
				return nil, false
			}
			current = next
		case []any:
			index, err := strconv.Atoi(part)
			if err != nil || index < 0 || index >= len(node) {
				return nil, false
			}
			current = node[index]
		default:
			return nil, false
		}
	}
	return current, current != nil
}

// Text renders a value as it appears inside a string: integral numbers
// without a fraction, objects and lists as JSON.
func Text(value any) string {
	switch v := value.(type) {
	case string:
		return v
	case float64:
		if v == float64(int64(v)) {
			return strconv.FormatInt(int64(v), 10)
		}
		return strconv.FormatFloat(v, 'f', -1, 64)
	case json.Number:
		return v.String()
	case bool:
		return strconv.FormatBool(v)
	case nil:
		return ""
	default:
		encoded, err := json.Marshal(v)
		if err != nil {
			return fmt.Sprint(v)
		}
		return string(encoded)
	}
}
