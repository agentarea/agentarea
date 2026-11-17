package replies_test

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"regexp"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/replies"
)

func TestTargetsOfATaskWithPushConfigs(t *testing.T) {
	ts, malformed := replies.Targets(runsapi.OutcomeTask{Parameters: map[string]any{
		"a2a_push_configs": []any{
			map[string]any{"id": "c1", "url": "https://client.test/hook"},
			map[string]any{"id": "c2"},
			"junk",
		},
	}})
	if len(ts) != 1 || len(malformed) != 2 {
		t.Fatalf("targets = %+v malformed = %v", ts, malformed)
	}
	p := ts[0]
	if p.Key != "a2a:c1" || p.Sender != replies.A2APushSender || p.Presentation != replies.Silent ||
		p.Config["type"] != replies.A2APushSender || p.Config["url"] != "https://client.test/hook" || p.Config["config_id"] != "c1" ||
		p.Config["presentation"] != replies.Silent {
		t.Fatalf("push target = %+v", p)
	}
}

var messageIDPattern = regexp.MustCompile(`"messageId": "([0-9a-f]{32})"`)

func TestA2APushBody(t *testing.T) {
	body, err := replies.A2APushBody(replies.Event{Type: "workflow.task.completed", TaskID: "t1",
		Data: map[string]any{"result": "done é", "context_id": "ctx1"}})
	if err != nil {
		t.Fatal(err)
	}
	m := messageIDPattern.FindStringSubmatch(body)
	if m == nil {
		t.Fatalf("no message id in %s", body)
	}
	want := `{"statusUpdate": {"taskId": "t1", "contextId": "ctx1", "status": {"state": "TASK_STATE_COMPLETED", ` +
		`"message": {"messageId": "` + m[1] + `", "role": "ROLE_AGENT", "parts": [{"text": "done \u00e9"}]}}}}`
	if body != want {
		t.Fatalf("body =\n%s\nwant\n%s", body, want)
	}
	body, _ = replies.A2APushBody(replies.Event{Type: "task.failed", Data: map[string]any{"task_id": "t2", "error": "boom"}})
	var parsed map[string]map[string]any
	if err := json.Unmarshal([]byte(body), &parsed); err != nil {
		t.Fatalf("%s: %v", body, err)
	}
	u := parsed["statusUpdate"]
	status, _ := u["status"].(map[string]any)
	if u["taskId"] != "t2" || u["contextId"] != "t2" || status["state"] != "TASK_STATE_FAILED" {
		t.Fatalf("failed = %s", body)
	}
	body, _ = replies.A2APushBody(replies.Event{Type: "task.cancelled", TaskID: "t3"})
	if body != `{"statusUpdate": {"taskId": "t3", "contextId": "t3", "status": {"state": "TASK_STATE_CANCELED"}}}` {
		t.Fatalf("cancelled = %s", body)
	}
	if body, _ := replies.A2APushBody(replies.Event{Type: "tool.call", TaskID: "t1"}); body != "" {
		t.Fatalf("a non-terminal event is pushed: %s", body)
	}
}

func pushSend(url string) replies.Send {
	return replies.Send{
		Event:  replies.Event{Type: "task.completed", ID: "ev1", TaskID: "t1"},
		Target: replies.Target{Key: "a2a:c1", Sender: replies.A2APushSender, Config: map[string]any{"url": url, "config_id": "c1"}},
		Owner:  "u1",
	}
}

func TestA2APushPostsWithItsToken(t *testing.T) {
	h := &hook{}
	srv := h.server(t)
	var asked string
	p := replies.A2APush{Client: srv.Client(), Secret: func(_ context.Context, _ scope.Workspace, owner, name string) (string, bool, error) {
		asked = owner + "/" + name
		return "tok", true, nil
	}}
	if err := p.Send(context.Background(), pushSend(srv.URL), `{"a":1}`); err != nil {
		t.Fatal(err)
	}
	if asked != "u1/a2a_push_token:t1:c1" || h.headers[0].Get(replies.A2ANotificationTokenHeader) != "tok" ||
		h.headers[0].Get("Content-Type") != "application/json" || h.bodies[0] != `{"a":1}` {
		t.Fatalf("asked %s headers %v body %q", asked, h.headers[0], h.bodies[0])
	}
}

func TestA2APushAnswers(t *testing.T) {
	h := &hook{}
	srv := h.server(t)
	p := replies.A2APush{Client: srv.Client(), Secret: func(context.Context, scope.Workspace, string, string) (string, bool, error) {
		return "", false, nil
	}}
	ctx := context.Background()
	if err := p.Send(ctx, pushSend(srv.URL), "{}"); err != nil || h.headers[0].Get(replies.A2ANotificationTokenHeader) != "" {
		t.Fatalf("without a token = %v %v", err, h.headers)
	}
	for status, fatal := range map[int]bool{500: false, 429: false, 404: true} {
		h.status = status
		err := p.Send(ctx, pushSend(srv.URL), "{}")
		if err == nil || replies.IsFatal(err) != fatal {
			t.Errorf("%d = %v", status, err)
		}
	}
	h.status = 0
	n := len(h.bodies)
	if err := p.Send(ctx, pushSend(srv.URL), ""); err != nil || len(h.bodies) != n {
		t.Fatalf("no body = %v, posted %d", err, len(h.bodies)-n)
	}
	broken := replies.A2APush{Client: srv.Client(), Secret: func(context.Context, scope.Workspace, string, string) (string, bool, error) {
		return "", false, fmt.Errorf("store down")
	}}
	if err := broken.Send(ctx, pushSend(srv.URL), "{}"); err == nil || replies.IsFatal(err) {
		t.Fatalf("an unreadable token store = %v", err)
	}
	unsafe := replies.A2APush{Secret: p.Secret, Client: &http.Client{Transport: roundTrip(func(*http.Request) (*http.Response, error) {
		return nil, fmt.Errorf("refused: %w", netguard.ErrUnsafe)
	})}}
	if err := unsafe.Send(ctx, pushSend("https://10.0.0.1/hook"), "{}"); !replies.IsFatal(err) {
		t.Fatalf("an unsafe url = %v", err)
	}
}

type roundTrip func(*http.Request) (*http.Response, error)

func (f roundTrip) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
