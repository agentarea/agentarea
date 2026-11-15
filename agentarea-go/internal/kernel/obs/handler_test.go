package obs

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"strings"
	"testing"
	"time"

	"go.opentelemetry.io/otel/trace"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
)

type logCase struct {
	Name   string          `json:"name"`
	Level  int             `json:"level"`
	Logger string          `json:"logger"`
	Msg    string          `json:"msg"`
	Args   []string        `json:"args"`
	Extra  json.RawMessage `json:"extra"`
	Traced bool            `json:"traced"`
	Line   string          `json:"line"`
}

func pyLevel(n int) slog.Level {
	switch n {
	case 10:
		return slog.LevelDebug
	case 20:
		return slog.LevelInfo
	case 30:
		return slog.LevelWarn
	case 40:
		return slog.LevelError
	}
	return LevelCritical
}

func attrOf(key string, v any) slog.Attr {
	switch x := v.(type) {
	case string:
		return slog.String(key, x)
	case json.Number:
		n, _ := x.Int64()
		return slog.Int64(key, n)
	case wirejson.Float:
		return slog.Float64(key, float64(x))
	case bool:
		return slog.Bool(key, x)
	}
	return slog.Any(key, v)
}

func TestHandlerMatchesPythonFormatter(t *testing.T) {
	raw, err := os.ReadFile("testdata/logging.json")
	if err != nil {
		t.Fatal(err)
	}
	var g struct {
		TraceID string    `json:"trace_id"`
		SpanID  string    `json:"span_id"`
		Cases   []logCase `json:"cases"`
	}
	if err := json.Unmarshal(raw, &g); err != nil {
		t.Fatal(err)
	}
	t.Setenv("TZ", "UTC")
	created := time.Date(2026, 11, 12, 10, 0, 0, 123456000, time.UTC)
	for _, c := range g.Cases {
		t.Run(c.Name, func(t *testing.T) {
			var buf bytes.Buffer
			h := NewHandler(&buf, HandlerOptions{Level: slog.LevelDebug, Logger: c.Logger})
			msg := c.Msg
			for _, a := range c.Args {
				msg = strings.Replace(msg, "%s", a, 1)
			}
			r := slog.NewRecord(created.In(time.Local), pyLevel(c.Level), msg, 0)
			extra, err := wirejson.Unmarshal(c.Extra)
			if err != nil {
				t.Fatal(err)
			}
			for _, m := range extra.(wirejson.Object) {
				r.AddAttrs(attrOf(m.Key, m.Value))
			}
			ctx := context.Background()
			if c.Traced {
				tid, _ := trace.TraceIDFromHex(g.TraceID)
				sid, _ := trace.SpanIDFromHex(g.SpanID)
				ctx = trace.ContextWithSpanContext(ctx, trace.NewSpanContext(trace.SpanContextConfig{
					TraceID: tid, SpanID: sid, TraceFlags: trace.FlagsSampled,
				}))
			}
			if err := h.Handle(ctx, r); err != nil {
				t.Fatal(err)
			}
			if got := strings.TrimSuffix(buf.String(), "\n"); got != c.Line {
				t.Errorf("\n got %s\nwant %s", got, c.Line)
			}
		})
	}
}

func TestHandlerContextAndException(t *testing.T) {
	var buf bytes.Buffer
	logger := slog.New(NewHandler(&buf, HandlerOptions{Logger: "agentarea.api", Now: time.Now}))
	ctx := WithRequest(context.Background(), "ws-1", "u-1")
	logger.ErrorContext(ctx, "Request failed: RuntimeError", KeyException, fmt.Sprintf("%+v", errors.New("boom")), "request_path", "/x")
	line := buf.String()
	for _, want := range []string{`"message": "Request failed: RuntimeError", "user_id": "u-1", "workspace_id": "ws-1", "exception": "boom", "taskName": null, "request_path": "/x"}`} {
		if !strings.Contains(line, want) {
			t.Fatalf("%s lacks %s", line, want)
		}
	}
	buf.Reset()
	text := slog.New(NewHandler(&buf, HandlerOptions{Text: true, Logger: "agentarea"}))
	text.Warn("token https://h/?token=abc")
	if !strings.HasSuffix(buf.String(), " - agentarea - WARNING - token https://h/?token=<redacted>\n") {
		t.Fatalf("text line %q", buf.String())
	}
}

func TestParseLevelAndNames(t *testing.T) {
	for _, name := range []string{"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} {
		l, err := ParseLevel(name)
		if err != nil || LevelName(l) != name {
			t.Errorf("%s: %v %v", name, LevelName(l), err)
		}
	}
	if _, err := ParseLevel("TRACE"); err == nil {
		t.Error("TRACE accepted")
	}
}

func TestInstrumentsMatchPython(t *testing.T) {
	raw, err := os.ReadFile("testdata/instruments.json")
	if err != nil {
		t.Fatal(err)
	}
	var py map[string]struct {
		Attributes []string  `json:"attributes"`
		Buckets    []float64 `json:"buckets"`
	}
	if err := json.Unmarshal(raw, &py); err != nil {
		t.Fatal(err)
	}
	ours := map[string]InstrumentPolicy{}
	for _, p := range Instruments() {
		if _, dup := ours[p.Name]; dup {
			t.Errorf("%s listed twice", p.Name)
		}
		ours[p.Name] = p
	}
	for name, want := range py {
		got, ok := ours[name]
		if !ok {
			t.Errorf("%s missing", name)
			continue
		}
		if fmt.Sprint(got.Attributes) != fmt.Sprint(want.Attributes) && name != HTTPServerDuration {
			t.Errorf("%s attributes %v, Python %v", name, got.Attributes, want.Attributes)
		}
		if fmt.Sprint(got.Buckets) != fmt.Sprint(want.Buckets) && len(want.Buckets)+len(got.Buckets) > 0 {
			t.Errorf("%s buckets %v, Python %v", name, got.Buckets, want.Buckets)
		}
	}
}
