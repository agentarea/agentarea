package handlers

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/service"
)

func TestProxySendForwardsOnlyMCPHeaders(t *testing.T) {
	var got *http.Request
	var gotBody string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got = r
		b, _ := io.ReadAll(r.Body)
		gotBody = string(b)
		w.Header().Set("Set-Cookie", "s=1")
		w.Header().Set("Mcp-Session-Id", "abc")
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusAccepted)
		_, _ = io.WriteString(w, "data: x\n\n")
	}))
	defer upstream.Close()

	in := httptest.NewRequest(http.MethodPost, "/v1/mcp/i/mcp?x=1", nil)
	in.Header.Set("Authorization", "Bearer caller")
	in.Header.Set("Cookie", "c=1")
	in.Header.Set("Accept", "application/json, text/event-stream")
	in.Header.Set("Mcp-Session-Id", "abc")
	in.Header.Set("X-Other", "y")
	up := service.Upstream{URL: upstream.URL + "/mcp", Transport: http.DefaultTransport, Headers: http.Header{"Authorization": {"Bearer upstream"}}}

	resp, err := proxySend(context.Background(), in, up, []byte(`{"a":1}`))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	if got.URL.RawQuery != "x=1" || gotBody != `{"a":1}` {
		t.Fatalf("query %q body %q", got.URL.RawQuery, gotBody)
	}
	if got.Header.Get("Authorization") != "Bearer upstream" || got.Header.Get("Cookie") != "" || got.Header.Get("X-Other") != "" {
		t.Fatalf("forwarded headers = %v", got.Header)
	}
	if got.Header.Get("Mcp-Session-Id") != "abc" || !strings.Contains(got.Header.Get("Accept"), "event-stream") {
		t.Fatalf("MCP headers dropped: %v", got.Header)
	}

	rec := httptest.NewRecorder()
	proxyRelay(rec, resp)
	if rec.Code != http.StatusAccepted || rec.Body.String() != "data: x\n\n" {
		t.Fatalf("relay: %d %q", rec.Code, rec.Body.String())
	}
	if rec.Header().Get("Set-Cookie") != "" || rec.Header().Get("Mcp-Session-Id") != "abc" {
		t.Fatalf("relayed headers = %v", rec.Header())
	}
}
