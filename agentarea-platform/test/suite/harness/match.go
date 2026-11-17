//go:build suite

package harness

import (
	"encoding/json"
	"fmt"
	"net/http"
	"reflect"
	"regexp"
	"sort"
	"strings"
	"time"
)

// Matcher stands in a wanted JSON value for a field that differs per run.
type Matcher interface {
	Match(got any) error
}

type matcherFunc struct {
	name string
	fn   func(any) error
}

func (m matcherFunc) Match(got any) error { return m.fn(got) }
func (m matcherFunc) String() string      { return m.name }

//nolint:gochecknoglobals // compiled once
var uuidRE = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

//nolint:gochecknoglobals // immutable matchers, used as values in wanted bodies
var (
	// Any matches any value, null included.
	Any Matcher = matcherFunc{"Any", func(any) error { return nil }}
	// AnyString matches any string.
	AnyString Matcher = matcherFunc{"AnyString", func(got any) error {
		if _, ok := got.(string); !ok {
			return fmt.Errorf("want a string, got %s", show(got))
		}
		return nil
	}}
	// AnyUUID matches a lowercase hyphenated UUID string.
	AnyUUID Matcher = matcherFunc{"AnyUUID", func(got any) error {
		if s, ok := got.(string); !ok || !uuidRE.MatchString(s) {
			return fmt.Errorf("want a UUID string, got %s", show(got))
		}
		return nil
	}}
	// AnyNumber matches any JSON number.
	AnyNumber Matcher = matcherFunc{"AnyNumber", func(got any) error {
		if _, ok := got.(json.Number); !ok {
			return fmt.Errorf("want a number, got %s", show(got))
		}
		return nil
	}}
	// AnyTimestamp matches an ISO 8601 date-time string, with or without zone.
	AnyTimestamp Matcher = matcherFunc{"AnyTimestamp", func(got any) error {
		s, ok := got.(string)
		if !ok {
			return fmt.Errorf("want a timestamp string, got %s", show(got))
		}
		for _, layout := range []string{time.RFC3339Nano, "2006-01-02T15:04:05.999999999", "2006-01-02 15:04:05.999999999"} {
			if _, err := time.Parse(layout, s); err == nil {
				return nil
			}
		}
		return fmt.Errorf("want a timestamp, got %q", s)
	}}
)

// Pattern matches a string against a regular expression.
func Pattern(expr string) Matcher {
	re := regexp.MustCompile(expr)
	return matcherFunc{"Pattern(" + expr + ")", func(got any) error {
		if s, ok := got.(string); !ok || !re.MatchString(s) {
			return fmt.Errorf("want a string matching %s, got %s", expr, show(got))
		}
		return nil
	}}
}

// Unordered matches an array holding exactly these elements in any order.
func Unordered(want ...any) Matcher {
	return matcherFunc{"Unordered", func(got any) error {
		arr, ok := got.([]any)
		if !ok {
			return fmt.Errorf("want an array, got %s", show(got))
		}
		if len(arr) != len(want) {
			return fmt.Errorf("want %d elements, got %d: %s", len(want), len(arr), show(got))
		}
		used := make([]bool, len(arr))
	next:
		for i, w := range want {
			for j, g := range arr {
				if !used[j] && Compare(g, w) == nil {
					used[j] = true
					continue next
				}
			}
			return fmt.Errorf("element %d of want (%s) not found in %s", i, show(w), show(got))
		}
		return nil
	}}
}

// Contains matches an array that holds each of want, among any others.
func Contains(want ...any) Matcher {
	return matcherFunc{"Contains", func(got any) error {
		arr, ok := got.([]any)
		if !ok {
			return fmt.Errorf("want an array, got %s", show(got))
		}
	next:
		for i, w := range want {
			for _, g := range arr {
				if Compare(g, w) == nil {
					continue next
				}
			}
			return fmt.Errorf("element %d of want (%s) not found in %s", i, show(w), show(got))
		}
		return nil
	}}
}

// Compare reports how got (a decoded JSON value) differs from want. want is
// built from map[string]any, []any, strings, bools, nil, Go numbers and
// Matchers. Objects compare by their full key set: a missing or an extra key
// is a difference. Arrays compare in order.
func Compare(got, want any) error {
	return compare("$", got, want)
}

func compare(path string, got, want any) error {
	switch w := want.(type) {
	case Matcher:
		if err := w.Match(got); err != nil {
			return fmt.Errorf("%s: %w", path, err)
		}
		return nil
	case map[string]any:
		g, ok := got.(map[string]any)
		if !ok {
			return fmt.Errorf("%s: want an object, got %s", path, show(got))
		}
		var missing, extra []string
		for k := range w {
			if _, ok := g[k]; !ok {
				missing = append(missing, k)
			}
		}
		for k := range g {
			if _, ok := w[k]; !ok {
				extra = append(extra, k)
			}
		}
		if len(missing) > 0 || len(extra) > 0 {
			sort.Strings(missing)
			sort.Strings(extra)
			return fmt.Errorf("%s: keys differ: missing %v, unexpected %v", path, missing, extra)
		}
		keys := make([]string, 0, len(w))
		for k := range w {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for _, k := range keys {
			if err := compare(path+"."+k, g[k], w[k]); err != nil {
				return err
			}
		}
		return nil
	case []any:
		g, ok := got.([]any)
		if !ok {
			return fmt.Errorf("%s: want an array, got %s", path, show(got))
		}
		if len(g) != len(w) {
			return fmt.Errorf("%s: want %d elements, got %d: %s", path, len(w), len(g), show(got))
		}
		for i := range w {
			if err := compare(fmt.Sprintf("%s[%d]", path, i), g[i], w[i]); err != nil {
				return err
			}
		}
		return nil
	case nil:
		if got != nil {
			return fmt.Errorf("%s: want null, got %s", path, show(got))
		}
		return nil
	case int, int64, float64:
		n, ok := got.(json.Number)
		if !ok || n.String() != fmt.Sprint(w) {
			return fmt.Errorf("%s: want %v, got %s", path, w, show(got))
		}
		return nil
	default:
		if !reflect.DeepEqual(got, want) {
			return fmt.Errorf("%s: want %s, got %s", path, show(want), show(got))
		}
		return nil
	}
}

func show(v any) string {
	if m, ok := v.(fmt.Stringer); ok {
		return m.String()
	}
	raw, err := json.Marshal(v)
	if err != nil {
		return fmt.Sprint(v)
	}
	s := string(raw)
	if len(s) > 300 {
		s = s[:300] + "..."
	}
	return strings.TrimSpace(s)
}

// Problem is the RFC 9457 body the backends answer errors with
// (agentarea_common/exceptions/handlers.py): want it with
// Response.Match(Problem(404, "http_error", "Project not found")).
func Problem(status int, code, detail string) map[string]any {
	return map[string]any{
		"type":   "about:blank",
		"title":  statusTitle(status),
		"status": status,
		"code":   code,
		"detail": detail,
	}
}

func statusTitle(status int) string {
	// Starlette uses http.HTTPStatus phrases, which differ from Go's for 422.
	if status == 422 {
		return "Unprocessable Content"
	}
	return http.StatusText(status)
}
