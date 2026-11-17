package events

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"time"
	"unicode/utf8"

	"github.com/google/uuid"
)

// Stream field names of the envelope (CloudEvents binary content mode,
// events/adapters/redis_streams.py encode). The payload is under "data".
const (
	FieldID              = "ce_id"
	FieldType            = "ce_type"
	FieldSource          = "ce_source"
	FieldTime            = "ce_time"
	FieldSpecVersion     = "ce_specversion"
	FieldDataContentType = "ce_datacontenttype"
	FieldSubject         = "ce_subject"
	FieldCorrelationID   = "ce_correlationid"
	FieldCausationID     = "ce_causationid"
	FieldTraceParent     = "ce_traceparent"
	FieldData            = "data"
)

const (
	defaultSpecVersion     = "1.0"
	defaultDataContentType = "application/json"
)

func envelopeField(name string) bool {
	switch name {
	case FieldID, FieldType, FieldSource, FieldTime, FieldSpecVersion, FieldDataContentType,
		FieldSubject, FieldCorrelationID, FieldCausationID, FieldTraceParent, "ce_data":
		return true
	}
	return false
}

func validExtension(name string) bool {
	if len(name) == 0 || len(name) > 20 {
		return false
	}
	for _, c := range []byte(name) {
		if (c < 'a' || c > 'z') && (c < '0' || c > '9') {
			return false
		}
	}
	return true
}

// Encode is an event's stream fields. An event with no id or time gets a new
// uuid4 and now, as the Python model's defaults give it.
func Encode(e IntegrationEvent) (map[string]string, error) {
	if e.ID == "" {
		e.ID = uuid.NewString()
	}
	if e.Time.IsZero() {
		e.Time = time.Now().UTC()
	}
	if e.SpecVersion == "" {
		e.SpecVersion = defaultSpecVersion
	}
	if e.DataContentType == "" {
		e.DataContentType = defaultDataContentType
	}
	data, err := PyJSON(dataOrEmpty(e.Data))
	if err != nil {
		return nil, fmt.Errorf("event %s data: %w", e.ID, err)
	}
	fields := map[string]string{
		FieldID:              e.ID,
		FieldType:            e.Type,
		FieldSource:          e.Source,
		FieldTime:            PyISO(e.Time),
		FieldSpecVersion:     e.SpecVersion,
		FieldDataContentType: e.DataContentType,
		FieldData:            data,
	}
	for k, v := range map[string]string{
		FieldSubject: e.Subject, FieldCorrelationID: e.CorrelationID,
		FieldCausationID: e.CausationID, FieldTraceParent: e.TraceParent,
	} {
		if v != "" {
			fields[k] = v
		}
	}
	for name, v := range e.Extensions {
		if !validExtension(name) || envelopeField("ce_"+name) {
			return nil, fmt.Errorf("CloudEvents extension name %q must be lowercase alphanumeric and not an envelope attribute", name)
		}
		fields["ce_"+name] = v
	}
	return fields, nil
}

func dataOrEmpty(d map[string]any) map[string]any {
	if d == nil {
		return map[string]any{}
	}
	return d
}

// ErrUndecodable marks stream fields that are not an event.
var ErrUndecodable = errors.New("undecodable event")

// Decode reads stream fields (events/adapters/redis_streams.py decode). A
// missing id or time is filled with a new uuid4 and now, as Python does.
func Decode(fields map[string]string) (IntegrationEvent, error) {
	var e IntegrationEvent
	typ, ok := fields[FieldType]
	if !ok {
		return e, fmt.Errorf("%w: no %s", ErrUndecodable, FieldType)
	}
	source, ok := fields[FieldSource]
	if !ok {
		return e, fmt.Errorf("%w: no %s", ErrUndecodable, FieldSource)
	}
	e.Type, e.Source = typ, source
	if id, ok := fields[FieldID]; ok {
		u, err := uuid.Parse(id)
		if err != nil {
			return e, fmt.Errorf("%w: %s: %w", ErrUndecodable, FieldID, err)
		}
		e.ID = u.String()
	} else {
		e.ID = uuid.NewString()
	}
	if t, ok := fields[FieldTime]; ok {
		parsed, err := ParsePyISO(t)
		if err != nil {
			return e, fmt.Errorf("%w: %s: %w", ErrUndecodable, FieldTime, err)
		}
		e.Time = parsed
	} else {
		e.Time = time.Now().UTC()
	}
	e.SpecVersion = valueOr(fields, FieldSpecVersion, defaultSpecVersion)
	e.DataContentType = valueOr(fields, FieldDataContentType, defaultDataContentType)
	e.Subject = fields[FieldSubject]
	e.CorrelationID = fields[FieldCorrelationID]
	e.CausationID = fields[FieldCausationID]
	e.TraceParent = fields[FieldTraceParent]
	e.Data = map[string]any{}
	if raw := fields[FieldData]; raw != "" {
		d := json.NewDecoder(bytes.NewReader([]byte(raw)))
		d.UseNumber()
		if err := d.Decode(&e.Data); err != nil {
			return e, fmt.Errorf("%w: data: %w", ErrUndecodable, err)
		}
	}
	e.Extensions = map[string]string{}
	for k, v := range fields {
		if len(k) > 3 && k[:3] == "ce_" && !envelopeField(k) {
			e.Extensions[k[3:]] = v
		}
	}
	return e, nil
}

func valueOr(fields map[string]string, k, def string) string {
	if v, ok := fields[k]; ok {
		return v
	}
	return def
}

// PyISO formats t as Python's datetime.isoformat() does for an aware
// datetime: microseconds, omitted when zero, and a ±HH:MM offset.
func PyISO(t time.Time) string {
	t = t.Truncate(time.Microsecond)
	var b []byte
	b = t.AppendFormat(b, "2006-01-02T15:04:05")
	if us := t.Nanosecond() / 1000; us != 0 {
		b = fmt.Appendf(b, ".%06d", us)
	}
	return string(t.AppendFormat(b, "-07:00"))
}

// ParsePyISO reads what Python's datetime.fromisoformat reads from our
// writers: RFC 3339 with any fraction, "Z" or an offset, or no offset (taken
// as UTC, as the Python side's naive timestamps are).
func ParsePyISO(s string) (time.Time, error) {
	for _, layout := range []string{time.RFC3339Nano, "2006-01-02T15:04:05.999999999", "2006-01-02 15:04:05.999999999Z07:00", "2006-01-02 15:04:05.999999999"} {
		if t, err := time.Parse(layout, s); err == nil {
			return t, nil
		}
	}
	return time.Time{}, fmt.Errorf("not an ISO 8601 time: %q", s)
}

// PyJSON is json.dumps(v) with Python's defaults: ", " and ": " separators
// and non-ASCII escaped (ensure_ascii). Object keys are sorted.
func PyJSON(v any) (string, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return "", err
	}
	return pyFormat(bytes.TrimRight(buf.Bytes(), "\n")), nil
}

func pyFormat(compact []byte) string {
	out := make([]byte, 0, len(compact)+len(compact)/8)
	inString, escaped := false, false
	for i := 0; i < len(compact); {
		c := compact[i]
		if c >= utf8.RuneSelf {
			r, size := utf8.DecodeRune(compact[i:])
			if r1, r2 := utf16Pair(r); r2 != 0 {
				out = appendU(appendU(out, r1), r2)
			} else {
				out = appendU(out, r1)
			}
			i += size
			continue
		}
		switch {
		case inString && c == 0x7f:
			out = append(out, `\u007f`...)
		case inString:
			switch {
			case escaped:
				escaped = false
			case c == '\\':
				escaped = true
			case c == '"':
				inString = false
			}
			out = append(out, c)
		case c == '"':
			inString = true
			out = append(out, c)
		case c == ',':
			out = append(out, ',', ' ')
		case c == ':':
			out = append(out, ':', ' ')
		default:
			out = append(out, c)
		}
		i++
	}
	return string(out)
}

func utf16Pair(r rune) (rune, rune) {
	if r < 0x10000 {
		return r, 0
	}
	r -= 0x10000
	return 0xD800 + (r>>10)&0x3FF, 0xDC00 + r&0x3FF
}

func appendU(b []byte, r rune) []byte {
	b = append(b, '\\', 'u')
	s := strconv.FormatInt(int64(r), 16)
	for range 4 - len(s) {
		b = append(b, '0')
	}
	return append(b, s...)
}
