package mcpclient

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
)

type rpcReq struct {
	ID     *int64         `json:"id"`
	Method string         `json:"method"`
	Params map[string]any `json:"params"`
}

// fakeServer is a streamable-HTTP MCP server; modern answers server/discover.
type fakeServer struct {
	modern    bool
	auth      string
	pages     int
	toolDelay time.Duration

	mu      sync.Mutex
	methods []string
	deleted bool
	headers []http.Header
}

func (f *fakeServer) seen() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string(nil), f.methods...)
}

func reply(w http.ResponseWriter, id *int64, result any, rpcErr map[string]any) {
	m := map[string]any{"jsonrpc": "2.0", "id": id}
	if rpcErr != nil {
		m["error"] = rpcErr
	} else {
		m["result"] = result
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(m)
}

func (f *fakeServer) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if f.auth != "" {
		w.Header().Set("WWW-Authenticate", f.auth)
		w.WriteHeader(http.StatusForbidden)
		return
	}
	if r.Method == http.MethodDelete {
		f.mu.Lock()
		f.deleted = r.Header.Get("Mcp-Session-Id") == "s1"
		f.mu.Unlock()
		return
	}
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	var req rpcReq
	_ = json.NewDecoder(r.Body).Decode(&req)
	f.mu.Lock()
	f.methods = append(f.methods, req.Method)
	f.headers = append(f.headers, r.Header.Clone())
	f.mu.Unlock()
	if req.ID == nil {
		w.WriteHeader(http.StatusAccepted)
		return
	}
	switch req.Method {
	case "server/discover":
		if !f.modern {
			reply(w, req.ID, nil, map[string]any{"code": CodeMethodNotFound, "message": "Method not found"})
			return
		}
		reply(w, req.ID, map[string]any{"supportedVersions": []string{ModernVersion},
			"capabilities": map[string]any{"tools": map[string]any{}}, "serverInfo": map[string]any{"name": "fake"}}, nil)
	case "initialize":
		w.Header().Set("Mcp-Session-Id", "s1")
		reply(w, req.ID, map[string]any{"protocolVersion": HandshakeVersion,
			"capabilities": map[string]any{"tools": map[string]any{}}, "serverInfo": map[string]any{"name": "fake"}}, nil)
	case "tools/list":
		page := 0
		if c, ok := req.Params["cursor"].(string); ok {
			_, _ = fmt.Sscanf(c, "p%d", &page)
		}
		res := map[string]any{"tools": []any{map[string]any{"name": fmt.Sprintf("t%d", page), "inputSchema": map[string]any{"type": "object"}}}}
		if page+1 < f.pages {
			res["nextCursor"] = fmt.Sprintf("p%d", page+1)
		}
		reply(w, req.ID, res, nil)
	case "tools/call":
		if f.toolDelay > 0 {
			select {
			case <-time.After(f.toolDelay):
			case <-r.Context().Done():
				return
			}
		}
		meta, _ := req.Params["_meta"].(map[string]any)
		token := meta["progressToken"]
		w.Header().Set("Content-Type", "text/event-stream")
		fl, _ := w.(http.Flusher)
		note, _ := json.Marshal(map[string]any{"jsonrpc": "2.0", "method": "notifications/progress",
			"params": map[string]any{"progressToken": token, "progress": 1, "total": 2, "message": "half"}})
		_, _ = fmt.Fprintf(w, "event: message\ndata: %s\n\n", note)
		if fl != nil {
			fl.Flush()
		}
		res, _ := json.Marshal(map[string]any{"jsonrpc": "2.0", "id": req.ID, "result": map[string]any{
			"content": []any{map[string]any{"type": "text", "text": "ok"}}, "structuredContent": map[string]any{"n": 1}}})
		_, _ = fmt.Fprintf(w, "event: message\ndata: %s\n\n", res)
	default:
		reply(w, req.ID, nil, map[string]any{"code": CodeMethodNotFound, "message": "Method not found"})
	}
}

func connect(t *testing.T, url string, rt http.RoundTripper) *Client {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	c, err := Connect(ctx, Options{URL: url, Transport: "streamable-http", RoundTripper: rt})
	if err != nil {
		t.Fatalf("connect: %v", err)
	}
	return c
}

func TestHandshakeEraListsAllPagesAndEndsTheSession(t *testing.T) {
	f := &fakeServer{pages: 3}
	srv := httptest.NewServer(f)
	defer srv.Close()
	c := connect(t, srv.URL+"/mcp", http.DefaultTransport)
	if c.ProtocolVersion() != HandshakeVersion {
		t.Fatalf("version %q", c.ProtocolVersion())
	}
	tools, err := c.ListTools(context.Background())
	if err != nil || len(tools) != 3 {
		t.Fatalf("tools %v err %v", tools, err)
	}
	c.Close()
	got := f.seen()
	want := []string{"server/discover", "initialize", "notifications/initialized", "tools/list", "tools/list", "tools/list"}
	if strings.Join(got, ",") != strings.Join(want, ",") {
		t.Fatalf("methods %v", got)
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	if !f.deleted {
		t.Fatal("session not deleted on close")
	}
	if f.headers[3].Get("Mcp-Session-Id") != "s1" {
		t.Fatal("session id not sent after initialize")
	}
}

func TestModernEraSkipsInitializeAndStampsHeaders(t *testing.T) {
	f := &fakeServer{modern: true, pages: 1}
	srv := httptest.NewServer(f)
	defer srv.Close()
	c := connect(t, srv.URL+"/mcp", http.DefaultTransport)
	defer c.Close()
	if c.ProtocolVersion() != ModernVersion {
		t.Fatalf("version %q", c.ProtocolVersion())
	}
	if _, err := c.ListTools(context.Background()); err != nil {
		t.Fatal(err)
	}
	got := f.seen()
	if strings.Join(got, ",") != "server/discover,tools/list" {
		t.Fatalf("methods %v", got)
	}
	f.mu.Lock()
	h := f.headers[1]
	f.mu.Unlock()
	if h.Get("Mcp-Protocol-Version") != ModernVersion || h.Get("Mcp-Method") != "tools/list" {
		t.Fatalf("headers %v", h)
	}
}

func TestVerdictCacheSkipsNegotiation(t *testing.T) {
	f := &fakeServer{modern: true, pages: 1}
	srv := httptest.NewServer(f)
	defer srv.Close()
	v := NewVerdicts(time.Hour)
	for range 2 {
		c, err := Connect(context.Background(), Options{URL: srv.URL + "/mcp", Transport: "streamable-http",
			RoundTripper: http.DefaultTransport, Verdicts: v, VerdictKey: "k"})
		if err != nil {
			t.Fatal(err)
		}
		c.Close()
	}
	n := 0
	for _, m := range f.seen() {
		if m == "server/discover" {
			n++
		}
	}
	if n != 1 {
		t.Fatalf("discover sent %d times", n)
	}
}

func TestUnauthorizedCarriesTheChallenge(t *testing.T) {
	f := &fakeServer{auth: `Bearer error="insufficient_scope", scope="https://www.googleapis.com/auth/gmail.readonly"`}
	srv := httptest.NewServer(f)
	defer srv.Close()
	_, err := Connect(context.Background(), Options{URL: srv.URL + "/x", RoundTripper: http.DefaultTransport})
	var un *UnauthorizedError
	if !errors.As(err, &un) {
		t.Fatalf("err %T %v", err, err)
	}
	if un.Status != 403 || !un.InsufficientScope || len(un.RequiredScopes) != 1 {
		t.Fatalf("%+v", un)
	}
	if IsTransient(err) {
		t.Fatal("a refusal is not transient")
	}
}

// legacySSEServer is the 2024-11-05 transport: a GET stream and a POST endpoint.
func legacySSEServer(t *testing.T) *httptest.Server {
	out := make(chan []byte, 16)
	mux := http.NewServeMux()
	mux.HandleFunc("GET /x/sse", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		fl := w.(http.Flusher)
		_, _ = fmt.Fprint(w, "event: endpoint\ndata: /x/messages?sid=1\n\n")
		fl.Flush()
		for {
			select {
			case m := <-out:
				_, _ = fmt.Fprintf(w, "event: message\ndata: %s\n\n", m)
				fl.Flush()
			case <-r.Context().Done():
				return
			}
		}
	})
	mux.HandleFunc("POST /x/messages", func(w http.ResponseWriter, r *http.Request) {
		var req rpcReq
		_ = json.NewDecoder(r.Body).Decode(&req)
		w.WriteHeader(http.StatusAccepted)
		if req.ID == nil {
			return
		}
		var res any
		switch req.Method {
		case "initialize":
			res = map[string]any{"protocolVersion": HandshakeVersion, "capabilities": map[string]any{}, "serverInfo": map[string]any{"name": "old"}}
		case "tools/list":
			res = map[string]any{"tools": []any{map[string]any{"name": "legacy"}}}
		default:
			raw, _ := json.Marshal(map[string]any{"jsonrpc": "2.0", "id": req.ID, "error": map[string]any{"code": CodeMethodNotFound, "message": "nope"}})
			out <- raw
			return
		}
		raw, _ := json.Marshal(map[string]any{"jsonrpc": "2.0", "id": req.ID, "result": res})
		out <- raw
	})
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return srv
}

func TestFallsBackToLegacySSE(t *testing.T) {
	srv := legacySSEServer(t)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	c, err := Connect(ctx, Options{URL: srv.URL + "/x", RoundTripper: http.DefaultTransport})
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	tools, err := c.ListTools(ctx)
	if err != nil || len(tools) != 1 || tools[0]["name"] != "legacy" {
		t.Fatalf("tools %v err %v", tools, err)
	}
}

func TestCallToolReportsProgressAndResult(t *testing.T) {
	srv := httptest.NewServer(&fakeServer{pages: 1})
	defer srv.Close()
	c := connect(t, srv.URL+"/mcp", http.DefaultTransport)
	defer c.Close()
	var got []Progress
	res, err := c.CallTool(context.Background(), Call{Name: "t0", Progress: func(p Progress) { got = append(got, p) }})
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got[0].Progress != 1 || got[0].Total == nil || *got[0].Total != 2 || got[0].Message != "half" {
		t.Fatalf("progress %+v", got)
	}
	if res.Content[0]["text"] != "ok" || res.StructuredContent == nil {
		t.Fatalf("result %+v", res)
	}
}

func TestCallToolTimeoutIsRequestTimeout(t *testing.T) {
	srv := httptest.NewServer(&fakeServer{pages: 1, toolDelay: 2 * time.Second})
	defer srv.Close()
	c := connect(t, srv.URL+"/mcp", http.DefaultTransport)
	defer c.Close()
	_, err := c.CallTool(context.Background(), Call{Name: "t0", Timeout: 100 * time.Millisecond})
	var rpc *RPCError
	if !errors.As(err, &rpc) || rpc.Code != CodeRequestTimeout || !IsTimeout(err) {
		t.Fatalf("err %v", err)
	}
}

func TestHandlerTransportServesInProcess(t *testing.T) {
	f := &fakeServer{pages: 2}
	c := connect(t, "http://mcp-gateway.internal/mcp/x/mcp", HandlerTransport(f))
	defer c.Close()
	tools, err := c.ListTools(context.Background())
	if err != nil || len(tools) != 2 {
		t.Fatalf("tools %v err %v", tools, err)
	}
	var got []Progress
	if _, err := c.CallTool(context.Background(), Call{Name: "t0", Progress: func(p Progress) { got = append(got, p) }}); err != nil || len(got) != 1 {
		t.Fatalf("call err %v progress %v", err, got)
	}
}

func TestGatewayRetryWaitsForStartAndClassifiesFailure(t *testing.T) {
	var mu sync.Mutex
	calls := 0
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		mu.Lock()
		calls++
		n := calls
		mu.Unlock()
		if n == 1 {
			w.Header().Set(StartingHeader, "1")
			w.Header().Set("Retry-After", "0")
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		_, _ = w.Write(body)
	})
	rt := GatewayRetry(HandlerTransport(h), 10*time.Second)
	req, _ := http.NewRequest(http.MethodPost, "http://mcp-gateway.internal/mcp/x/mcp", strings.NewReader("payload"))
	resp, err := rt.RoundTrip(req)
	if err != nil {
		t.Fatal(err)
	}
	got, _ := io.ReadAll(resp.Body)
	_ = resp.Body.Close()
	if string(got) != "payload" || calls != 2 {
		t.Fatalf("body %q calls %d", got, calls)
	}

	failing := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set(StartFailureHeader, "image pull failed")
		w.WriteHeader(http.StatusServiceUnavailable)
	})
	req, _ = http.NewRequest(http.MethodPost, "http://mcp-gateway.internal/mcp/x/mcp", strings.NewReader("{}"))
	_, err = GatewayRetry(HandlerTransport(failing), time.Second).RoundTrip(req)
	var sf *StartupFailureError
	if !errors.As(err, &sf) || sf.Detail != "image pull failed" {
		t.Fatalf("err %v", err)
	}
}

func TestIsTransient(t *testing.T) {
	cases := []struct {
		err  error
		want bool
	}{
		{&net.OpError{Op: "dial", Err: errors.New("connection refused")}, true},
		{fmt.Errorf("x: %w", context.DeadlineExceeded), true},
		{&net.OpError{Op: "dial", Err: &netguard.BlockedError{}}, false},
		{&RPCError{Code: CodeInternalError}, false},
		{&StartupFailureError{Detail: "x"}, false},
		{&HTTPError{Status: 500}, false},
		{errors.New("other"), false},
	}
	for i, c := range cases {
		if got := IsTransient(c.err); got != c.want {
			t.Errorf("case %d (%v): got %v", i, c.err, got)
		}
	}
}

func TestSplitContentKeepsSupportedImages(t *testing.T) {
	text, imgs := SplitContent([]map[string]any{
		{"type": "text", "text": "a"},
		{"type": "image", "mimeType": "image/png", "data": "aGk="},
		{"type": "image", "mimeType": "image/tiff", "data": "aGk="},
		{"type": "text", "text": "b"},
	})
	if !strings.Contains(text, "a") || !strings.Contains(text, "b") || len(imgs) != 1 || imgs[0].MimeType != "image/png" {
		t.Fatalf("text %q images %+v", text, imgs)
	}
}

func TestErrorsLeaveOutTheURLQuery(t *testing.T) {
	srv := httptest.NewServer(http.NotFoundHandler())
	dead := srv.URL
	srv.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_, err := Connect(ctx, Options{URL: dead + "/mcp?api_key=s3cret", Transport: "streamable-http",
		RoundTripper: http.DefaultTransport})
	if err == nil || strings.Contains(err.Error(), "s3cret") {
		t.Fatalf("Connect to a dead server = %v, want an error without the query", err)
	}
	if !IsTransient(err) {
		t.Fatalf("IsTransient(%v) = false, want the dial failure kept", err)
	}
	he := &HTTPError{URL: "https://u:p@mcp.example/sse?token=s3cret#frag", Status: 500}
	if got := he.Error(); strings.Contains(got, "s3cret") || strings.Contains(got, "u:p") ||
		!strings.Contains(got, "https://mcp.example/sse") {
		t.Fatalf("HTTPError.Error() = %q", got)
	}
}
