package obs

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"strings"
	"sync"
	"time"

	"go.opentelemetry.io/otel/trace"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
)

// Handler writes Python's log lines. JSON is WorkspaceContextFormatter
// (json.dumps with its defaults, default=str); text is the "standard"
// formatter, "%(asctime)s - %(name)s - %(levelname)s - %(message)s".
// Messages and top-level string attributes are redacted, then the message
// sanitized, as the console handler's filters do.
type Handler struct {
	out      *output
	level    slog.Leveler
	text     bool
	logger   string
	redactor *SecretRedactor
	attrs    []slog.Attr
	groups   []string
	now      func() time.Time
}

type output struct {
	mu sync.Mutex
	w  io.Writer
}

// HandlerOptions configure NewHandler.
type HandlerOptions struct {
	// Level is the lowest level written.
	Level slog.Leveler
	// Text selects the plain formatter (AGENTAREA_LOG_FORMAT=text).
	Text bool
	// Logger is the "logger" field (Python's logger name).
	Logger string
	// Now stands in for the clock in tests.
	Now func() time.Time
}

// NewHandler writes to w.
func NewHandler(w io.Writer, opts HandlerOptions) *Handler {
	h := &Handler{
		out: &output{w: w}, level: opts.Level, text: opts.Text, logger: opts.Logger,
		redactor: NewSecretRedactor(), now: opts.Now,
	}
	if h.level == nil {
		h.level = slog.LevelInfo
	}
	if h.now == nil {
		h.now = time.Now
	}
	return h
}

// WithLogger is h writing under another logger name.
func (h *Handler) WithLogger(name string) *Handler {
	c := *h
	c.logger = name
	return &c
}

// Enabled implements slog.Handler.
func (h *Handler) Enabled(_ context.Context, l slog.Level) bool { return l >= h.level.Level() }

// WithAttrs implements slog.Handler.
func (h *Handler) WithAttrs(attrs []slog.Attr) slog.Handler {
	if len(attrs) == 0 {
		return h
	}
	c := *h
	c.attrs = append(append([]slog.Attr(nil), h.attrs...), nest(h.groups, attrs)...)
	return &c
}

// WithGroup implements slog.Handler.
func (h *Handler) WithGroup(name string) slog.Handler {
	if name == "" {
		return h
	}
	c := *h
	c.groups = append(append([]string(nil), h.groups...), name)
	return &c
}

// nest puts attrs inside the open groups, innermost last.
func nest(groups []string, attrs []slog.Attr) []slog.Attr {
	for i := len(groups) - 1; i >= 0; i-- {
		attrs = []slog.Attr{{Key: groups[i], Value: slog.GroupValue(attrs...)}}
	}
	return attrs
}

// LevelName is Python's levelname.
func LevelName(l slog.Level) string {
	switch {
	case l >= LevelCritical:
		return "CRITICAL"
	case l >= slog.LevelError:
		return "ERROR"
	case l >= slog.LevelWarn:
		return "WARNING"
	case l >= slog.LevelInfo:
		return "INFO"
	default:
		return "DEBUG"
	}
}

// ParseLevel reads AGENTAREA_LOG_LEVEL's names.
func ParseLevel(name string) (slog.Level, error) {
	switch strings.ToUpper(name) {
	case "DEBUG":
		return slog.LevelDebug, nil
	case "INFO":
		return slog.LevelInfo, nil
	case "WARNING":
		return slog.LevelWarn, nil
	case "ERROR":
		return slog.LevelError, nil
	case "CRITICAL":
		return LevelCritical, nil
	}
	return 0, fmt.Errorf("unknown log level %q", name)
}

// FormatTime is logging.Formatter.formatTime's default: local time,
// "2006-01-02 15:04:05,000".
func FormatTime(t time.Time) string {
	t = t.Local()
	return t.Format("2006-01-02 15:04:05") + fmt.Sprintf(",%03d", t.Nanosecond()/int(time.Millisecond))
}

// Handle implements slog.Handler.
func (h *Handler) Handle(ctx context.Context, r slog.Record) error {
	ts := r.Time
	if ts.IsZero() {
		ts = h.now()
	}
	msg := Sanitize(h.redactor.RedactString(r.Message))
	attrs := make([]slog.Attr, 0, len(h.attrs)+r.NumAttrs())
	attrs = append(attrs, h.attrs...)
	var recAttrs []slog.Attr
	r.Attrs(func(a slog.Attr) bool {
		recAttrs = append(recAttrs, a)
		return true
	})
	attrs = append(attrs, nest(h.groups, recAttrs)...)

	if h.text {
		line := FormatTime(ts) + " - " + h.logger + " - " + LevelName(r.Level) + " - " + msg
		for _, a := range attrs {
			if a.Key == KeyException {
				line += "\n" + h.redactor.RedactString(a.Value.Resolve().String())
			}
		}
		return h.write([]byte(line + "\n"))
	}

	entry := wirejson.Object{
		{Key: KeyTimestamp, Value: FormatTime(ts)},
		{Key: KeyLevel, Value: LevelName(r.Level)},
		{Key: KeyLogger, Value: h.logger},
		{Key: KeyMessage, Value: msg},
	}
	hoisted := map[string]any{}
	var extras wirejson.Object
	for _, a := range inline(attrs) {
		v := h.value(a)
		switch a.Key {
		case KeyUserID, KeyWorkspaceID, KeyException, "audit_event":
			hoisted[a.Key] = v
			continue
		}
		extras.Set(a.Key, v)
	}
	if ws, user, ok := RequestFrom(ctx); ok {
		if _, set := hoisted[KeyUserID]; !set && user != "" {
			hoisted[KeyUserID] = user
		}
		if _, set := hoisted[KeyWorkspaceID]; !set && ws != "" {
			hoisted[KeyWorkspaceID] = ws
		}
	}
	for _, k := range []string{KeyUserID, KeyWorkspaceID} {
		if v, ok := hoisted[k]; ok {
			entry = append(entry, wirejson.Member{Key: k, Value: v})
		}
	}
	if sc := trace.SpanContextFromContext(ctx); sc.IsValid() {
		entry = append(entry,
			wirejson.Member{Key: KeyTraceID, Value: sc.TraceID().String()},
			wirejson.Member{Key: KeySpanID, Value: sc.SpanID().String()})
	}
	for _, k := range []string{KeyException, "audit_event"} {
		if v, ok := hoisted[k]; ok {
			entry = append(entry, wirejson.Member{Key: k, Value: v})
		}
	}
	// LogRecord always carries taskName (None outside an asyncio task); it
	// is the first of the record's own attributes the formatter copies.
	entry = append(entry, wirejson.Member{Key: "taskName", Value: nil})
	for _, m := range extras {
		entry.Set(m.Key, m.Value)
	}
	line, err := wirejson.Marshal(entry, wirejson.Dumps)
	if err != nil {
		line, _ = wirejson.Marshal(wirejson.Object{
			{Key: KeyTimestamp, Value: FormatTime(ts)},
			{Key: KeyLevel, Value: LevelName(r.Level)},
			{Key: KeyLogger, Value: h.logger},
			{Key: KeyMessage, Value: msg},
			{Key: "log_error", Value: err.Error()},
		}, wirejson.Dumps)
	}
	return h.write(append(line, '\n'))
}

// inline drops empty attributes and opens groups without a key, as slog
// handlers do.
func inline(attrs []slog.Attr) []slog.Attr {
	out := make([]slog.Attr, 0, len(attrs))
	for _, a := range attrs {
		a.Value = a.Value.Resolve()
		switch {
		case a.Value.Kind() == slog.KindGroup && a.Key == "":
			out = append(out, inline(a.Value.Group())...)
		case a.Key == "":
		default:
			out = append(out, a)
		}
	}
	return out
}

func (h *Handler) write(b []byte) error {
	h.out.mu.Lock()
	defer h.out.mu.Unlock()
	_, err := h.out.w.Write(b)
	return err
}

// value renders an attribute as json.dumps(default=str) would see it;
// top-level strings are redacted.
func (h *Handler) value(a slog.Attr) any {
	v := a.Value.Resolve()
	switch v.Kind() {
	case slog.KindString:
		return h.redactor.Redact(a.Key, v).String()
	case slog.KindInt64:
		return v.Int64()
	case slog.KindUint64:
		return v.Uint64()
	case slog.KindFloat64:
		return wirejson.Float(v.Float64())
	case slog.KindBool:
		return v.Bool()
	case slog.KindDuration:
		return v.Duration().String()
	case slog.KindTime:
		return PyDatetime(v.Time())
	case slog.KindGroup:
		obj := wirejson.Object{}
		for _, g := range v.Group() {
			if g.Key == "" {
				continue
			}
			obj.Set(g.Key, plainValue(g.Value))
		}
		return obj
	case slog.KindAny, slog.KindLogValuer:
		return anyValue(v.Any())
	}
	return anyValue(v.Any())
}

func plainValue(v slog.Value) any {
	v = v.Resolve()
	switch v.Kind() {
	case slog.KindString:
		return v.String()
	case slog.KindInt64:
		return v.Int64()
	case slog.KindUint64:
		return v.Uint64()
	case slog.KindFloat64:
		return wirejson.Float(v.Float64())
	case slog.KindBool:
		return v.Bool()
	case slog.KindDuration:
		return v.Duration().String()
	case slog.KindTime:
		return PyDatetime(v.Time())
	case slog.KindGroup:
		obj := wirejson.Object{}
		for _, g := range v.Group() {
			obj.Set(g.Key, plainValue(g.Value))
		}
		return obj
	case slog.KindAny, slog.KindLogValuer:
		return anyValue(v.Any())
	}
	return anyValue(v.Any())
}

// anyValue is default=str: a value JSON cannot hold becomes its string.
func anyValue(x any) any {
	switch t := x.(type) {
	case nil:
		return nil
	case error:
		return t.Error()
	case float32:
		return wirejson.Float(float64(t))
	case float64:
		return wirejson.Float(t)
	case fmt.Stringer:
		return t.String()
	}
	if b, err := json.Marshal(x); err == nil {
		return json.RawMessage(b)
	}
	return fmt.Sprint(x)
}

// PyDatetime is str(datetime): "2026-11-12 10:00:00.123456+00:00", the
// microseconds only when there are some.
func PyDatetime(t time.Time) string {
	s := t.Format("2006-01-02 15:04:05")
	if us := t.Nanosecond() / 1000; us != 0 {
		s += fmt.Sprintf(".%06d", us)
	}
	return s + t.Format("-07:00")
}

// Logs is the process's Logging.
type Logs struct{ h *Handler }

// NewLogging builds Logging writing to w with level and format (json or
// text) as config.Common carries them.
func NewLogging(w io.Writer, level, format string) (*Logs, error) {
	l, err := ParseLevel(level)
	if err != nil {
		return nil, err
	}
	if format != "json" && format != "text" {
		return nil, fmt.Errorf("unknown log format %q", format)
	}
	return &Logs{h: NewHandler(w, HandlerOptions{Level: l, Text: format == "text"})}, nil
}

// Logger is a logger whose lines carry component as "logger".
func (l *Logs) Logger(component string) *slog.Logger { return slog.New(l.h.WithLogger(component)) }

var _ Logging = (*Logs)(nil)
