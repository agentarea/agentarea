package domain

import (
	"encoding/json"
	"fmt"
	"reflect"
	"strings"
)

// EventFilter is which events a subscription receives: kinds and dotted-path field values.
// Empty kinds and fields match every event.
type EventFilter struct {
	Kinds  []string
	Fields map[string]any
	// SourceType and SessionKey narrow an external subscriber's filter (ExternalFilter).
	SourceType *string
	SessionKey *string
}

// ParseEventFilter is EventFilter.model_validate (extra="forbid"): nil is the empty filter.
func ParseEventFilter(v any) (EventFilter, error) {
	f := EventFilter{Kinds: []string{}, Fields: map[string]any{}}
	if v == nil {
		return f, nil
	}
	m, ok := v.(map[string]any)
	if !ok {
		return f, Invalid("event_filter: Input should be a valid dictionary or instance of EventFilter")
	}
	for k, val := range m {
		switch k {
		case "kinds":
			list, ok := val.([]any)
			if !ok {
				if ss, isStrs := val.([]string); isStrs {
					f.Kinds = append(f.Kinds, ss...)
					continue
				}
				return f, Invalid("event_filter.kinds: Input should be a valid list")
			}
			for i, item := range list {
				s, ok := item.(string)
				if !ok {
					return f, Invalid(fmt.Sprintf("event_filter.kinds.%d: Input should be a valid string", i))
				}
				f.Kinds = append(f.Kinds, s)
			}
		case "fields":
			fm, ok := val.(map[string]any)
			if !ok {
				return f, Invalid("event_filter.fields: Input should be a valid dictionary")
			}
			f.Fields = fm
		default:
			return f, Invalid(fmt.Sprintf("event_filter.%s: Extra inputs are not permitted", k))
		}
	}
	return f, nil
}

// ValidateEventFilter refuses what EventFilter refuses.
func ValidateEventFilter(f map[string]any) error {
	if f == nil {
		return nil
	}
	_, err := ParseEventFilter(f)
	return err
}

// StoredFilter reads a stored filter leniently: unknown keys and wrong shapes are dropped.
func StoredFilter(m map[string]any) EventFilter {
	f := EventFilter{Kinds: []string{}, Fields: map[string]any{}}
	if list, ok := m["kinds"].([]any); ok {
		for _, item := range list {
			if s, ok := item.(string); ok {
				f.Kinds = append(f.Kinds, s)
			}
		}
	}
	if fm, ok := m["fields"].(map[string]any); ok {
		f.Fields = fm
	}
	if s, ok := m["source_type"].(string); ok {
		f.SourceType = &s
	}
	if s, ok := m["session_key"].(string); ok {
		f.SessionKey = &s
	}
	return f
}

// Dump is model_dump(): the shape every subscription row stores.
func (f EventFilter) Dump() map[string]any {
	kinds := make([]any, len(f.Kinds))
	for i, k := range f.Kinds {
		kinds[i] = k
	}
	fields := f.Fields
	if fields == nil {
		fields = map[string]any{}
	}
	out := map[string]any{"kinds": kinds, "fields": fields}
	if f.SourceType != nil || f.SessionKey != nil {
		out["source_type"] = ptrAny(f.SourceType)
		out["session_key"] = ptrAny(f.SessionKey)
	}
	return out
}

func ptrAny(p *string) any {
	if p == nil {
		return nil
	}
	return *p
}

func kindMatches(kind, allowed string) bool {
	return kind == allowed || strings.HasPrefix(kind, allowed+".") || strings.HasPrefix(allowed, kind+".")
}

// ValueAt is the value at a dotted path in event data, nil when absent; body.* reads raw_data
// for a legacy generic webhook that carries no body.
func ValueAt(data map[string]any, path string) (any, bool) {
	parts := strings.Split(path, ".")
	if parts[0] == "body" {
		if _, hasBody := data["body"]; !hasBody {
			if _, hasRaw := data["raw_data"]; hasRaw {
				parts[0] = "raw_data"
			}
		}
	}
	var v any = data
	for _, p := range parts {
		m, ok := v.(map[string]any)
		if !ok {
			return nil, false
		}
		if v, ok = m[p]; !ok {
			return nil, false
		}
	}
	return v, true
}

// Matches is EventFilter.matches over an event's kind and data.
func (f EventFilter) Matches(kind string, data map[string]any) bool {
	if len(f.Kinds) > 0 {
		ok := false
		for _, k := range f.Kinds {
			if kindMatches(kind, k) {
				ok = true
				break
			}
		}
		if !ok {
			return false
		}
	}
	for path, want := range f.Fields {
		got, _ := ValueAt(data, path)
		if !JSONEqual(got, want) {
			return false
		}
	}
	return true
}

// Admits is the filter applied to an event, external narrowing included.
func (f EventFilter) Admits(e Event) bool {
	if !f.Matches(e.Kind, e.Data) {
		return false
	}
	if f.SourceType != nil && (e.SourceType == nil || *e.SourceType != *f.SourceType) {
		return false
	}
	if f.SessionKey != nil && (e.SessionKey == nil || *e.SessionKey != *f.SessionKey) {
		return false
	}
	return true
}

// JSONEqual is Python == over decoded JSON: 1 == 1.0, True == 1.
func JSONEqual(a, b any) bool {
	an, aNum := number(a)
	bn, bNum := number(b)
	if aNum && bNum {
		return an == bn
	}
	switch av := a.(type) {
	case map[string]any:
		bv, ok := b.(map[string]any)
		if !ok || len(av) != len(bv) {
			return false
		}
		for k, x := range av {
			y, ok := bv[k]
			if !ok || !JSONEqual(x, y) {
				return false
			}
		}
		return true
	case []any:
		bv, ok := b.([]any)
		if !ok || len(av) != len(bv) {
			return false
		}
		for i := range av {
			if !JSONEqual(av[i], bv[i]) {
				return false
			}
		}
		return true
	}
	return reflect.DeepEqual(a, b)
}

func number(v any) (float64, bool) {
	switch n := v.(type) {
	case float64:
		return n, true
	case int:
		return float64(n), true
	case int64:
		return float64(n), true
	case json.Number:
		f, err := n.Float64()
		return f, err == nil
	case bool:
		if n {
			return 1, true
		}
		return 0, true
	}
	return 0, false
}
