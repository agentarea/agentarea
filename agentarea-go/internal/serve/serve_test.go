package serve

import (
	"bufio"
	"context"
	"errors"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/lifecycle"
)

func quietLog() *slog.Logger { return slog.New(slog.DiscardHandler) }

func testConfig(t *testing.T) Config {
	t.Helper()
	l := config.FromMap(map[string]string{"HOST": "127.0.0.1", "PORT": "0"})
	c := LoadConfig(l)
	if err := l.Err(); err != nil {
		t.Fatal(err)
	}
	return c
}

func edge(t *testing.T, opts Options, modules ...Module) *httptest.Server {
	t.Helper()
	a, err := Assemble(testConfig(t), opts, quietLog(), modules...)
	if err != nil {
		t.Fatal(err)
	}
	s := httptest.NewServer(a.Handler)
	t.Cleanup(s.Close)
	return s
}

func call(t *testing.T, method, url string) (*http.Response, string) {
	t.Helper()
	req, err := http.NewRequestWithContext(t.Context(), method, url, nil)
	if err != nil {
		t.Fatal(err)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	b, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatal(err)
	}
	return resp, string(b)
}

type failing struct{}

func (failing) Name() string                { return "db" }
func (failing) Check(context.Context) error { return errors.New("down") }

func TestRootAndHealthRoutes(t *testing.T) {
	clock := func() time.Time { return time.Date(2026, 11, 11, 21, 17, 18, 165722000, time.Local) }
	s := edge(t, Options{Version: "0.1.1", Now: clock})
	cases := []struct{ path, body string }{
		{"/", `{"message":"AgentArea API is running."}`},
		{"/health", `{"status":"healthy","version":"0.1.1","timestamp":"2026-11-11T21:17:18.165722"}`},
		{LivePath, `{"status":"ok"}`},
		{ReadyPath, `{"status":"ok"}`},
	}
	for _, c := range cases {
		resp, body := call(t, "GET", s.URL+c.path)
		if resp.StatusCode != 200 || body != c.body || resp.Header.Get("Content-Type") != "application/json" {
			t.Errorf("%s: %d %s %q", c.path, resp.StatusCode, resp.Header.Get("Content-Type"), body)
		}
	}
}

func TestIsoformatDropsZeroMicroseconds(t *testing.T) {
	if got := isoformat(time.Date(2026, 1, 2, 3, 4, 5, 999, time.UTC)); got != "2026-01-02T03:04:05" {
		t.Fatal(got)
	}
	if got := isoformat(time.Date(2026, 1, 2, 3, 4, 5, 1000, time.UTC)); got != "2026-01-02T03:04:05.000001" {
		t.Fatal(got)
	}
}

func TestReadyFailsWithAFailingCheck(t *testing.T) {
	s := edge(t, Options{Checks: []lifecycle.Checker{failing{}}})
	resp, body := call(t, "GET", s.URL+ReadyPath)
	if resp.StatusCode != 503 || body != `{"status":"unavailable","failed":{"db":"down"}}` {
		t.Fatalf("%d %s", resp.StatusCode, body)
	}
	if resp, _ := call(t, "GET", s.URL+LivePath); resp.StatusCode != 200 {
		t.Fatalf("livez %d", resp.StatusCode)
	}
}

func TestUnknownRouteIs404Problem(t *testing.T) {
	s := edge(t, Options{})
	resp, body := call(t, "GET", s.URL+"/v1/workspaces/acme/agents/")
	if resp.StatusCode != 404 || resp.Header.Get("Content-Type") != httpx.ProblemMediaType ||
		body != `{"type":"about:blank","title":"Not Found","status":404,"code":"http_error","detail":"Not Found"}` {
		t.Fatalf("%d %s %s", resp.StatusCode, resp.Header.Get("Content-Type"), body)
	}
	resp, _ = call(t, "POST", s.URL+"/health")
	if resp.StatusCode != 405 || resp.Header.Get("Content-Type") != httpx.ProblemMediaType {
		t.Fatalf("405: %d", resp.StatusCode)
	}
}

var errGone = errors.New("gone")

// TestModulesMount covers both kinds of registration: a hand route on the
// Router and a route on the chi tree (what a generated server does), plus
// the module's error mapper.
func TestModulesMount(t *testing.T) {
	m := Module{
		Name: "projects",
		Errors: func(err error) (*httpx.Error, bool) {
			if errors.Is(err, errGone) {
				return httpx.NewError(http.StatusGone, "gone", "project gone"), true
			}
			return nil, false
		},
		Mount: func(rt Routes) error {
			rt.Mux.Handle("GET /v1/workspaces/{workspace}/files/download/{file_path...}",
				http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					_, _ = io.WriteString(w, r.PathValue("workspace")+":"+r.PathValue("file_path"))
				}))
			rt.Mux.Chi().Get("/v1/workspaces/{workspace}/projects/{project_id}", func(w http.ResponseWriter, r *http.Request) {
				rt.Errors.Write(w, r, errGone)
			})
			return nil
		},
	}
	s := edge(t, Options{}, m)
	if _, body := call(t, "GET", s.URL+"/v1/workspaces/acme/files/download/a/b.txt"); body != "acme:a/b.txt" {
		t.Errorf("hand route: %q", body)
	}
	resp, body := call(t, "GET", s.URL+"/v1/workspaces/acme/projects/p1")
	if resp.StatusCode != 410 || !strings.Contains(body, `"code":"gone"`) {
		t.Errorf("mapped error: %d %s", resp.StatusCode, body)
	}
}

func TestMountErrorsNameTheModule(t *testing.T) {
	for name, m := range map[string]Module{
		"bad pattern": {Name: "agents", Mount: func(rt Routes) error {
			rt.Mux.Handle("/no-method", http.NotFoundHandler())
			return nil
		}},
		"returns error": {Name: "agents", Mount: func(Routes) error { return errors.New("boom") }},
		"no mount":      {Name: "agents"},
	} {
		_, err := Assemble(testConfig(t), Options{}, quietLog(), m)
		if err == nil || !strings.Contains(err.Error(), "agents") {
			t.Errorf("%s: %v", name, err)
		}
	}
}

func TestLoadConfig(t *testing.T) {
	l := config.FromMap(map[string]string{"PORT": "9000", "AGENTAREA_API_MAX_BODY": "1024"})
	c := LoadConfig(l)
	if err := l.Err(); err != nil {
		t.Fatal(err)
	}
	if c.Addr != "0.0.0.0:9000" || c.Edge.MaxBody != 1024 {
		t.Fatalf("%+v", c)
	}
	l = config.FromMap(map[string]string{"PORT": "70000"})
	LoadConfig(l)
	if l.Err() == nil {
		t.Fatal("port 70000 accepted")
	}
}

// TestServerStopEndsStreamsAndUpgrades runs the component as the role does:
// stopping it ends an open event stream and a hijacked connection.
func TestServerStopEndsStreamsAndUpgrades(t *testing.T) {
	m := Module{Name: "runs", Mount: func(rt Routes) error {
		rt.Mux.Handle("GET /v1/runner/connect", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			conn, rw, err := http.NewResponseController(w).Hijack()
			if err != nil {
				return
			}
			defer func() { _ = conn.Close() }()
			_, _ = rw.WriteString("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
			_ = rw.Flush()
			<-r.Context().Done()
		}))
		rt.Mux.Handle("GET /v1/workspaces/{workspace}/streams/events/live", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "text/event-stream")
			_, _ = io.WriteString(w, "data: 1\n\n")
			_ = http.NewResponseController(w).Flush()
			<-r.Context().Done()
		}))
		return nil
	}}
	srv, err := New(testConfig(t), Options{}, quietLog(), m)
	if err != nil {
		t.Fatal(err)
	}
	g := lifecycle.NewGroup(lifecycle.Options{StartupTimeout: time.Second, ShutdownTimeout: 300 * time.Millisecond})
	g.Add(srv)
	ctx, stop := context.WithCancel(t.Context())
	ran := make(chan error, 1)
	go func() { ran <- g.Run(ctx) }()
	deadline := time.Now().Add(5 * time.Second)
	for srv.Addr() == nil && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if srv.Addr() == nil {
		t.Fatal("not started")
	}
	addr := srv.Addr().String()

	conn, err := (&net.Dialer{}).DialContext(t.Context(), "tcp", addr)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = conn.Close() }()
	_, _ = io.WriteString(conn, "GET /v1/runner/connect HTTP/1.1\r\nHost: x\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n")
	br := bufio.NewReader(conn)
	if resp, err := http.ReadResponse(br, nil); err != nil || resp.StatusCode != 101 {
		t.Fatalf("upgrade: %v", err)
	}

	req, _ := http.NewRequestWithContext(t.Context(), "GET", "http://"+addr+"/v1/workspaces/w/streams/events/live", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	sr := bufio.NewReader(resp.Body)
	if line, _ := sr.ReadString('\n'); line != "data: 1\n" {
		t.Fatalf("event %q", line)
	}

	stop()
	select {
	case err := <-ran:
		if err != nil {
			t.Fatalf("run: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("did not stop")
	}
	_ = conn.SetReadDeadline(time.Now().Add(5 * time.Second))
	if _, err := br.ReadByte(); err == nil {
		t.Error("upgraded connection still open after stop")
	}
	if _, err := io.ReadAll(sr); err != nil && !errors.Is(err, io.ErrUnexpectedEOF) {
		t.Logf("stream ended with %v", err)
	}
}
