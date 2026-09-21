package mcpgateway

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/agentarea/mcp-manager/internal/usage"
)

type usageRecorderStub struct {
	mu     sync.Mutex
	events []usage.Event
}

func (r *usageRecorderStub) Record(_ context.Context, event usage.Event) error {
	if err := event.Validate(); err != nil {
		return err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	r.events = append(r.events, event)
	return nil
}

func (r *usageRecorderStub) snapshot() []usage.Event {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]usage.Event(nil), r.events...)
}

type usageRuntimeStub struct{ endpoint string }

func (r usageRuntimeStub) EnsureReady(context.Context, *models.MCPServerInstance) (string, error) {
	return r.endpoint, nil
}
func (r usageRuntimeStub) Delete(context.Context, *models.MCPServerInstance) error { return nil }

func TestUsageTracksConcurrentHTTPRequestsWithoutInspectingBodies(t *testing.T) {
	const secret = "private-payload-must-not-be-recorded" // pragma: allowlist secret
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(r.Body)
		if err != nil || string(body) != secret {
			t.Errorf("upstream body = %q, err=%v", body, err)
		}
		w.WriteHeader(http.StatusAccepted)
	}))
	defer upstream.Close()
	instance := &models.MCPServerInstance{InstanceID: "8ca9f331-9cc9-4a51-9933-27d7bb73860b", WorkspaceID: "ws-usage"}
	g := testGateway(t, &gatewayRepositoryStub{instance: instance}, usageRuntimeStub{endpoint: upstream.URL})
	recorder := &usageRecorderStub{}
	g.SetUsageRecorder(recorder)
	var group sync.WaitGroup
	for range 8 {
		group.Add(1)
		go func() {
			defer group.Done()
			r := httptest.NewRequest(http.MethodPost, "/mcp/"+instance.InstanceID+"/mcp", strings.NewReader(secret))
			r.Header.Set("X-AgentArea-Manager-Authorization", "Bearer "+testGatewaySecret)
			w := httptest.NewRecorder()
			g.ServeHTTP(w, r)
			if w.Code != http.StatusAccepted {
				t.Errorf("status = %d", w.Code)
			}
		}()
	}
	group.Wait()
	pairs := map[string]map[string]usage.Event{}
	for _, event := range recorder.snapshot() {
		if event.WorkspaceID != instance.WorkspaceID || event.ResourceID != instance.InstanceID {
			t.Fatalf("incorrect attribution: %+v", event)
		}
		if strings.Contains(string(event.Data), secret) || strings.Contains(string(event.Data), testGatewaySecret) {
			t.Fatal("usage contains request content or credential")
		}
		var data struct {
			RequestID string    `json:"request_id"`
			Method    string    `json:"http_method"`
			Transport string    `json:"transport"`
			Status    int       `json:"http_status"`
			Duration  int64     `json:"duration_ns"`
			Start     time.Time `json:"started_at"`
			End       time.Time `json:"ended_at"`
		}
		if err := json.Unmarshal(event.Data, &data); err != nil {
			t.Fatal(err)
		}
		if data.Method != http.MethodPost || data.Transport != "streamable_http" {
			t.Fatalf("transport facts = %+v", data)
		}
		if event.Kind == "mcp.request.completed" && (data.Status != http.StatusAccepted || data.Duration <= 0 || data.End.Before(data.Start)) {
			t.Fatalf("completion = %+v", data)
		}
		if pairs[data.RequestID] == nil {
			pairs[data.RequestID] = map[string]usage.Event{}
		}
		if _, exists := pairs[data.RequestID][event.Kind]; exists {
			t.Fatalf("duplicate request fact: %s", event.ID)
		}
		pairs[data.RequestID][event.Kind] = event
	}
	if len(pairs) != 8 {
		t.Fatalf("distinct requests = %d", len(pairs))
	}
	for id, pair := range pairs {
		if len(pair) != 2 || pair["mcp.request.started"].ID == "" || pair["mcp.request.completed"].ID == "" {
			t.Fatalf("request %s facts = %+v", id, pair)
		}
	}
}

func TestUsageSSEStartRemainsOpenWhileResponseStreams(t *testing.T) {
	release := make(chan struct{})
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, "data: first\n\n")
		w.(http.Flusher).Flush()
		select {
		case <-release:
		case <-r.Context().Done():
		}
	}))
	defer upstream.Close()
	defer close(release)
	instance := &models.MCPServerInstance{InstanceID: "8ca9f331-9cc9-4a51-9933-27d7bb73860b", WorkspaceID: "ws-usage"}
	g := testGateway(t, &gatewayRepositoryStub{instance: instance}, usageRuntimeStub{endpoint: upstream.URL})
	recorder := &usageRecorderStub{}
	g.SetUsageRecorder(recorder)
	server := httptest.NewServer(g)
	defer server.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	r, _ := http.NewRequestWithContext(ctx, http.MethodGet, server.URL+"/mcp/"+instance.InstanceID+"/mcp", nil)
	r.Header.Set("X-AgentArea-Manager-Authorization", "Bearer "+testGatewaySecret)
	response, err := http.DefaultClient.Do(r)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	chunk := make([]byte, len("data: first\n\n"))
	if _, err := io.ReadFull(response.Body, chunk); err != nil {
		t.Fatal(err)
	}
	if string(chunk) != "data: first\n\n" {
		t.Fatalf("stream = %q", chunk)
	}
	events := recorder.snapshot()
	if len(events) != 1 || events[0].Kind != "mcp.request.started" {
		t.Fatalf("open SSE facts = %+v", events)
	}
	var data map[string]any
	if err := json.Unmarshal(events[0].Data, &data); err != nil {
		t.Fatal(err)
	}
	if data["http_method"] != "GET" || data["transport"] != "streamable_http" {
		t.Fatalf("SSE is not transport: %+v", data)
	}
	if _, exists := data["duration_ns"]; exists {
		t.Fatal("unfinished request has a fabricated duration")
	}
}

func TestRuntimeUsageDoesNotCreateAllocationForWarmRequests(t *testing.T) {
	backend := &runtimeBackendStub{statuses: []statusReply{{err: backends.ErrInstanceNotFound}, {status: "running"}}}
	provider := &runtimeProviderStub{}
	runtime := testProviderRuntime(t, backend, provider, time.Second)
	recorder := &usageRecorderStub{}
	runtime.SetUsageRecorder(recorder)
	instance := dockerInstance()
	instance.WorkspaceID = "ws-usage"
	for range 4 {
		if _, err := runtime.EnsureReady(context.Background(), instance); err != nil {
			t.Fatal(err)
		}
	}
	events := recorder.snapshot()
	if len(events) != 3 || events[0].Kind != "mcp.runtime.creation.started" || events[1].Kind != "mcp.runtime.creation.completed" || events[2].Kind != "runtime.sample" {
		t.Fatalf("warm requests multiplied creation facts: %+v", events)
	}
	if err := runtime.Delete(context.Background(), instance); err != nil {
		t.Fatal(err)
	}
	backend.mu.Lock()
	backend.statusCall = 0
	backend.mu.Unlock()
	if _, err := runtime.EnsureReady(context.Background(), instance); err != nil {
		t.Fatal(err)
	}
	events = recorder.snapshot()
	if len(events) != 8 || events[4].Kind != "mcp.runtime.deletion.completed" || events[5].Kind != "mcp.runtime.creation.started" || events[5].ID == events[0].ID {
		t.Fatalf("restart facts = %+v", events)
	}
}

type abortingUsageWriter struct{ *httptest.ResponseRecorder }

func (w abortingUsageWriter) Write([]byte) (int, error) { panic(http.ErrAbortHandler) }

func TestUsageDoesNotInventCompletionAfterProxyAbort(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(w, "response")
	}))
	defer upstream.Close()
	instance := &models.MCPServerInstance{InstanceID: "8ca9f331-9cc9-4a51-9933-27d7bb73860b", WorkspaceID: "ws-usage"}
	repository := &gatewayRepositoryStub{instance: instance}
	g := testGateway(t, repository, usageRuntimeStub{endpoint: upstream.URL})
	recorder := &usageRecorderStub{}
	g.SetUsageRecorder(recorder)
	request := httptest.NewRequest(http.MethodPost, "/mcp/"+instance.InstanceID+"/mcp", nil)
	request.Header.Set("X-AgentArea-Manager-Authorization", "Bearer "+testGatewaySecret)
	var aborted any
	func() {
		defer func() { aborted = recover() }()
		g.ServeHTTP(abortingUsageWriter{httptest.NewRecorder()}, request)
	}()
	if aborted != http.ErrAbortHandler {
		t.Fatalf("proxy abort = %v", aborted)
	}
	events := recorder.snapshot()
	if len(events) != 1 || events[0].Kind != "mcp.request.started" {
		t.Fatalf("aborted request got fabricated completion: %+v", events)
	}
	if repository.finished != 1 {
		t.Fatal("aborted stream leaked its live request lease")
	}
}
