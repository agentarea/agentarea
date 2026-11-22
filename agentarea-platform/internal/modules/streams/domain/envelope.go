package domain

import (
	"math"
	"net/mail"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

// FallbackKind is the kind of an event whose entry names none that renders.
const FallbackKind = "event"

var credentialHeaderRE = regexp.MustCompile(`(?i)^x-.*-(token|secret)$|signature|api-?key`)

// EventFields is what the platform reads off an inbound event by its entry's templates.
type EventFields struct {
	Kind string
	// Key is nil when the event carries nothing that names it.
	Key *string
	// SessionKey is "<source_id>:<value>", nil when the provider has no sessions.
	SessionKey    *string
	Sender        *string
	OccurredAt    *time.Time
	Depth         *string
	CorrelationID *string
	CausationID   *string
}

// WithoutCredentials is the headers an event keeps: none that carries a credential or a
// signature over one.
func WithoutCredentials(headers map[string]string, v *Verification) map[string]string {
	signed := ""
	if v != nil && v.Header != nil {
		signed = strings.ToLower(*v.Header)
	}
	out := make(map[string]string, len(headers))
	for name, value := range headers {
		low := strings.ToLower(name)
		switch low {
		case "authorization", "cookie", "set-cookie", "proxy-authorization":
			continue
		}
		if (signed != "" && low == signed) || credentialHeaderRE.MatchString(name) {
			continue
		}
		out[name] = value
	}
	return out
}

func pick(override, own Template) Template {
	if override != nil {
		return override
	}
	return own
}

func optional(t Template, c TemplateContext) *string {
	if v, ok := RenderFirst(t, c); ok {
		return &v
	}
	return nil
}

// MaxSummaryRunes is the longest summary an event shows.
const MaxSummaryRunes = 512

// summaryOf is the first template that renders to a non-blank line.
func summaryOf(t Template, c TemplateContext) *string {
	for _, tpl := range t {
		if v, ok := Render(tpl, c); ok {
			if s := oneLine(&v, MaxSummaryRunes); s != nil {
				return s
			}
		}
	}
	return nil
}

// EventSummary is one line of what a recorded event says by its source's summary template or
// else its entry's, read off the headers and body it keeps; nil when none renders or the body
// is stored as a file.
func EventSummary(e SourceTypeEntry, o EventOverrides, data map[string]any) *string {
	headers := map[string]string{}
	if h, ok := data["headers"].(map[string]any); ok {
		for k, v := range h {
			if text, ok := v.(string); ok {
				headers[k] = text
			}
		}
	}
	return summaryOf(pick(o.Summary, e.Event.Summary), TemplateContext{Body: data["body"], Headers: headers})
}

// SummaryLine is s as one line of at most MaxSummaryRunes, nil when nothing is left.
func SummaryLine(s string) *string {
	return oneLine(&s, MaxSummaryRunes)
}

// oneLine is s with whitespace runs collapsed to one space, cut at max runes; nil when nothing is left.
func oneLine(s *string, max int) *string {
	if s == nil {
		return nil
	}
	r := []rune(strings.Join(strings.Fields(*s), " "))
	if len(r) > max {
		r = r[:max]
	}
	if len(r) == 0 {
		return nil
	}
	v := string(r)
	return &v
}

// ReadEvent is kind, key, session, sender and time of one event by the entry's templates; a
// source's own templates stand in for the entry's kind, key and session key.
func ReadEvent(e SourceTypeEntry, o EventOverrides, sourceID string, headers map[string]string, body any) EventFields {
	c := TemplateContext{Body: body, Headers: headers}
	t := e.Event
	f := EventFields{
		Kind:          FallbackKind,
		Key:           optional(pick(o.Key, t.Key), c),
		Sender:        optional(t.Sender, c),
		Depth:         optional(t.Depth, c),
		CorrelationID: optional(t.CorrelationID, c),
		CausationID:   optional(t.CausationID, c),
	}
	if k, ok := RenderFirst(pick(o.Kind, t.Kind), c); ok && k != "" {
		f.Kind = k
	}
	if s := optional(pick(o.SessionKey, t.SessionKey), c); s != nil {
		v := sourceID + ":" + *s
		f.SessionKey = &v
	}
	if at := optional(t.OccurredAt, c); at != nil {
		f.OccurredAt = ProviderTime(*at)
	}
	return f
}

var countRE = regexp.MustCompile(`^[0-9]+$`)

// CarriedDepth is one more than the producer's depth, capped at one over limit; false when
// value is not a count.
func CarriedDepth(value string, limit int) (int, bool) {
	if !countRE.MatchString(value) {
		return 0, false
	}
	n, err := strconv.Atoi(value)
	if err != nil || n > limit {
		n = limit
	}
	return n + 1, true
}

// ChainID is a carried correlation or causation id in canonical form, false when not a UUID.
func ChainID(value string) (string, bool) {
	id, err := CanonicalUUID(value)
	return id, err == nil
}

func isoLayouts() []string {
	return []string{
		"2006-01-02T15:04:05.999999999Z07:00", "2006-01-02T15:04:05.999999999",
		"2006-01-02 15:04:05.999999999Z07:00", "2006-01-02 15:04:05.999999999",
		"2006-01-02T15:04Z07:00", "2006-01-02T15:04", "2006-01-02 15:04Z07:00", "2006-01-02 15:04",
		"2006-01-02T15Z07:00", "2006-01-02T15", "2006-01-02",
		"20060102T150405Z07:00", "20060102T150405", "20060102",
	}
}

// ProviderTime is a provider's own time: unix seconds (or milliseconds past 1e11), ISO 8601 or
// RFC 2822; nil when it is none of them or out of range. A time without a zone is UTC.
func ProviderTime(value string) *time.Time {
	text := strings.TrimSpace(value)
	if n, err := strconv.ParseFloat(strings.ReplaceAll(text, "_", ""), 64); err == nil {
		if math.IsNaN(n) || math.IsInf(n, 0) {
			return nil
		}
		secs := n
		if n > 1e11 {
			secs = n / 1000
		}
		if math.Abs(secs) > 253402300799 {
			return nil
		}
		whole, frac := math.Modf(secs)
		micros := math.RoundToEven(frac * 1e6)
		t := time.Unix(int64(whole), int64(micros)*1000).UTC()
		return &t
	}
	iso := strings.ReplaceAll(text, "Z", "+00:00")
	for _, layout := range isoLayouts() {
		if t, err := time.Parse(layout, iso); err == nil {
			return &t
		}
	}
	if t, err := mail.ParseDate(text); err == nil {
		return &t
	}
	return nil
}

const (
	eachValue = ".*"
	lastItem  = "[-1]"
)

func listPath(path string) string {
	return strings.TrimSuffix(strings.TrimSuffix(path, eachValue), lastItem)
}

func empty(v any) bool {
	switch x := v.(type) {
	case nil:
		return true
	case []any:
		return len(x) == 0
	case map[string]any:
		return len(x) == 0
	}
	return false
}

// AttachmentPath is the first of the entry's attachment paths present in the body.
func AttachmentPath(e SourceTypeEntry, body any) (string, bool) {
	if e.Event.Attachments == nil {
		return "", false
	}
	for _, p := range strings.Split(e.Event.Attachments.Path, "|") {
		p = strings.TrimSpace(p)
		if p != "" && !empty(PathValue(body, listPath(p))) {
			return p, true
		}
	}
	return "", false
}

// AttachmentItems is the file objects at path: a list of them or one, each value of path.*, or
// the last entry of path[-1].
func AttachmentItems(body any, path string) []map[string]any {
	objects := func(list []any) []map[string]any {
		out := []map[string]any{}
		for _, item := range list {
			if m, ok := item.(map[string]any); ok {
				out = append(out, m)
			}
		}
		return out
	}
	if p, ok := strings.CutSuffix(path, eachValue); ok {
		m, isMap := PathValue(body, p).(map[string]any)
		if !isMap {
			return []map[string]any{}
		}
		keys := make([]string, 0, len(m))
		for k := range m {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		values := make([]any, 0, len(m))
		for _, k := range keys {
			values = append(values, m[k])
		}
		return objects(values)
	}
	if p, ok := strings.CutSuffix(path, lastItem); ok {
		list, isList := PathValue(body, p).([]any)
		if !isList || len(list) == 0 {
			return []map[string]any{}
		}
		return objects(list[len(list)-1:])
	}
	switch v := PathValue(body, path).(type) {
	case map[string]any:
		return []map[string]any{v}
	case []any:
		return objects(v)
	}
	return []map[string]any{}
}
