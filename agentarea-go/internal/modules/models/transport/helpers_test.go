package transport

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"sync"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/domain"
)

type capture struct {
	mu     sync.Mutex
	hits   int
	path   string
	header http.Header
	body   map[string]any
}

func (c *capture) snapshot() (int, string, http.Header, map[string]any) {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.hits, c.path, c.header, c.body
}

func (c *capture) record(t *testing.T, r *http.Request) {
	t.Helper()
	raw, err := io.ReadAll(r.Body)
	if err != nil {
		t.Errorf("read request body: %v", err)
	}
	var body map[string]any
	if err := json.Unmarshal(raw, &body); err != nil {
		t.Errorf("request body is not a JSON object: %v: %s", err, raw)
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	c.hits++
	c.path = r.URL.Path
	c.header = r.Header.Clone()
	c.body = body
}

// serveRaw answers every request with status and body as given.
func serveRaw(t *testing.T, status int, body string) (*httptest.Server, *capture) {
	t.Helper()
	c := &capture{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		c.record(t, r)
		if status >= 400 {
			w.Header().Set("Content-Type", "application/json")
		} else {
			w.Header().Set("Content-Type", "text/event-stream")
		}
		w.WriteHeader(status)
		_, _ = io.WriteString(w, body)
	}))
	t.Cleanup(srv.Close)
	return srv, c
}

// openAISSE is the body _serve_sse writes: each event as a data line, then [DONE].
func openAISSE(events ...string) string {
	var b strings.Builder
	for _, e := range events {
		b.WriteString("data: " + e + "\n\n")
	}
	b.WriteString("data: [DONE]\n\n")
	return b.String()
}

// anthropicSSE is the body the Anthropic _serve writes: an event line and a data line per event.
func anthropicSSE(t *testing.T, events ...string) string {
	t.Helper()
	var b strings.Builder
	for _, e := range events {
		var head struct {
			Type string `json:"type"`
		}
		if err := json.Unmarshal([]byte(e), &head); err != nil {
			t.Fatalf("fixture event is not JSON: %v: %s", err, e)
		}
		b.WriteString("event: " + head.Type + "\ndata: " + e + "\n\n")
	}
	return b.String()
}

func profile(t *testing.T, p domain.Profile) domain.Profile {
	t.Helper()
	out, err := domain.NewProfile(p)
	if err != nil {
		t.Fatalf("NewProfile: %v", err)
	}
	return out
}

func dec(s string) *money.Decimal {
	d := money.MustParse(s)
	return &d
}

func userHi() []api.Message { return []api.Message{{Role: "user", Content: "hi"}} }

// outcome is what _complete_from_stream folds the deltas into.
type outcome struct {
	deltas    []Delta
	content   string
	reasoning string
	toolCalls []api.ToolCall
	usage     *Usage
	cost      money.Decimal
	finish    string
}

func runStream(ctx context.Context, m Model, r Request) (outcome, error) {
	var o outcome
	err := m.Stream(ctx, r, func(d Delta) error {
		o.deltas = append(o.deltas, d)
		o.content += d.Content
		o.reasoning += d.Reasoning
		if len(d.ToolCalls) > 0 {
			o.toolCalls = d.ToolCalls
		}
		if d.Usage != nil {
			o.usage = d.Usage
			o.cost = d.Cost
		}
		if d.FinishReason != "" {
			o.finish = d.FinishReason
		}
		return nil
	})
	return o, err
}

// jsonValue decodes s as encoding/json does a request body, for comparison.
func jsonValue(t *testing.T, s string) any {
	t.Helper()
	var v any
	if err := json.Unmarshal([]byte(s), &v); err != nil {
		t.Fatalf("bad JSON literal: %v: %s", err, s)
	}
	return v
}

// numObj decodes s as the transport does a stream chunk (numbers as json.Number).
func numObj(t *testing.T, s string) map[string]any {
	t.Helper()
	d := json.NewDecoder(strings.NewReader(s))
	d.UseNumber()
	var v map[string]any
	if err := d.Decode(&v); err != nil {
		t.Fatalf("bad JSON literal: %v: %s", err, s)
	}
	return v
}

func assertJSON(t *testing.T, label string, got any, want string) {
	t.Helper()
	raw, err := json.Marshal(got)
	if err != nil {
		t.Fatalf("%s: marshal: %v", label, err)
	}
	g := jsonValue(t, string(raw))
	w := jsonValue(t, want)
	if !reflect.DeepEqual(g, w) {
		t.Errorf("%s:\n got  %s\n want %s", label, raw, want)
	}
}

func assertCost(t *testing.T, label string, got money.Decimal, want string) {
	t.Helper()
	if got.Cmp(money.MustParse(want)) != 0 {
		t.Errorf("%s = %s, want %s", label, got, want)
	}
}
