package httpx

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
)

type sseGolden struct {
	Frames []struct {
		Name      string          `json:"name"`
		EventType string          `json:"event_type"`
		Data      json.RawMessage `json:"data"`
		EventID   *string         `json:"event_id"`
		Frame     string          `json:"frame"`
	} `json:"frames"`
	Heartbeat []string `json:"heartbeat_sequence"`
	Response  struct {
		Status  int               `json:"status"`
		Headers map[string]string `json:"headers"`
		Body    string            `json:"body"`
	} `json:"response"`
}

func loadSSE(t *testing.T) sseGolden {
	t.Helper()
	raw, err := os.ReadFile("testdata/sse.json")
	if err != nil {
		t.Fatal(err)
	}
	var g sseGolden
	if err := json.Unmarshal(raw, &g); err != nil {
		t.Fatal(err)
	}
	return g
}

func TestFormatSSEMatchesPython(t *testing.T) {
	for _, f := range loadSSE(t).Frames {
		data, err := wirejson.Unmarshal(f.Data)
		if err != nil {
			t.Fatal(err)
		}
		id := ""
		if f.EventID != nil {
			id = *f.EventID
		}
		got, err := FormatSSE(f.EventType, data, id)
		if err != nil {
			t.Fatal(err)
		}
		if string(got) != f.Frame {
			t.Errorf("%s:\n got %q\nwant %q", f.Name, got, f.Frame)
		}
	}
}

func TestSSEResponseMatchesPython(t *testing.T) {
	g := loadSSE(t)
	req := httptest.NewRequest("GET", "/stream", nil)
	req.Header.Set("Last-Event-ID", "41")
	rec := httptest.NewRecorder()
	s, err := StartSSE(rec, req)
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Event("x", wirejson.Object{{Key: "last", Value: LastEventID(req)}}, "1"); err != nil {
		t.Fatal(err)
	}
	if rec.Code != g.Response.Status || rec.Body.String() != g.Response.Body {
		t.Fatalf("%d %q, Python %d %q", rec.Code, rec.Body.String(), g.Response.Status, g.Response.Body)
	}
	for k, v := range g.Response.Headers {
		if got := rec.Header().Get(k); got != v {
			t.Errorf("header %s = %q, Python %q", k, got, v)
		}
	}
}

func TestPumpHeartbeatsMatchPython(t *testing.T) {
	g := loadSSE(t)
	rec := httptest.NewRecorder()
	s, err := StartSSE(rec, httptest.NewRequest("GET", "/", nil))
	if err != nil {
		t.Fatal(err)
	}
	frames := make(chan []byte)
	go func() {
		frames <- []byte("event: a\ndata: {}\n\n")
		time.Sleep(500 * time.Millisecond)
		frames <- []byte("event: b\ndata: {}\n\n")
		close(frames)
	}()
	if err := s.Pump(context.Background(), frames, 200*time.Millisecond); err != nil {
		t.Fatal(err)
	}
	if got, want := rec.Body.String(), strings.Join(g.Heartbeat, ""); got != want {
		t.Fatalf("got %q, Python %q", got, want)
	}
}

func TestPumpStopsWithContext(t *testing.T) {
	rec := httptest.NewRecorder()
	s, _ := StartSSE(rec, httptest.NewRequest("GET", "/", nil))
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := s.Pump(ctx, make(chan []byte), time.Second); !errors.Is(err, context.Canceled) {
		t.Fatalf("got %v", err)
	}
}

type fakeLimiter struct {
	allowed bool
	retry   int
	err     error
}

func (f fakeLimiter) Take(context.Context, string, string, int) (bool, int, error) {
	return f.allowed, f.retry, f.err
}

func TestEnforceRateLimit(t *testing.T) {
	ctx := context.Background()
	if err := EnforceRateLimit(ctx, fakeLimiter{allowed: true}, nil, "a2a", "ip:1", 300); err != nil {
		t.Fatal(err)
	}
	if err := EnforceRateLimit(ctx, fakeLimiter{err: errors.New("down")}, nil, "a2a", "ip:1", 300); err != nil {
		t.Fatalf("fail-open: %v", err)
	}
	err := EnforceRateLimit(ctx, fakeLimiter{retry: 0}, nil, "a2a", "ip:1", 300)
	rec := httptest.NewRecorder()
	NewErrors("http://x", nil).Write(rec, httptest.NewRequest("GET", "/", nil), err)
	want := `{"type":"about:blank","title":"Too Many Requests","status":429,"code":"http_error","detail":"Rate limit exceeded"}`
	if rec.Code != http.StatusTooManyRequests || rec.Body.String() != want || rec.Header().Get("Retry-After") != "1" {
		t.Fatalf("%d %q %v", rec.Code, rec.Body.String(), rec.Header())
	}
	if k := RateLimitKey("a2a", "ip:1"); !strings.HasPrefix(k, "agentarea:rate-limit:a2a:") || len(k) != len("agentarea:rate-limit:a2a:")+64 {
		t.Fatalf("key %s", k)
	}
}
