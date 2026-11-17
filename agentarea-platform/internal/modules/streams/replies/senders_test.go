package replies_test

import (
	"bufio"
	"context"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/replies"
)

func intp(n int) *int { return &n }

func TestTargetsOfATask(t *testing.T) {
	ts, malformed := replies.Targets(runsapi.OutcomeTask{
		Parameters: map[string]any{"delivery_address": map[string]any{"type": "slack", "sender": "http"}},
		Metadata: map[string]any{"task_webhook": map[string]any{"url": "https://x.test/hook", "signed": true},
			"end_user_id": "eu1", "app_metadata": map[string]any{"k": "v"}},
	})
	if len(malformed) != 0 || len(ts) != 2 {
		t.Fatalf("targets = %+v malformed = %v", ts, malformed)
	}
	if ts[0].Key != replies.AddressTarget || ts[0].Sender != "http" || ts[0].Presentation != replies.Concise {
		t.Fatalf("address = %+v", ts[0])
	}
	w := ts[1]
	if w.Key != replies.TaskWebhookTarget || w.Presentation != replies.Silent || w.Config["signed"] != true ||
		w.Config["url"] != "https://x.test/hook" || w.Data["end_user_id"] != "eu1" {
		t.Fatalf("webhook = %+v", w)
	}
	ts, malformed = replies.Targets(runsapi.OutcomeTask{Parameters: map[string]any{"delivery_address": map[string]any{"type": "slack"}}})
	if len(ts) != 0 || len(malformed) != 1 {
		t.Fatalf("a delivery address without sender = %+v %v", ts, malformed)
	}
}

func TestVisibility(t *testing.T) {
	for _, c := range []struct {
		event, presentation string
		want                bool
	}{
		{"task.completed", replies.Silent, true},
		{"workflow.task.failed", replies.Silent, true},
		{"approval.requested", replies.Silent, false},
		{"approval.requested", replies.Summary, true},
		{"tool.call", replies.Concise, true},
		{"tool.call", replies.Summary, false},
		{"llm.call.chunk", replies.Concise, false},
		{"llm.call.chunk", replies.Verbose, true},
		{"task.progress", replies.Verbose, false},
	} {
		if got := replies.Visible(c.event, c.presentation); got != c.want {
			t.Errorf("Visible(%s, %s) = %v", c.event, c.presentation, got)
		}
	}
}

func TestFormatEvent(t *testing.T) {
	slack, _ := replies.MarkupNamed("slack")
	tg, _ := replies.MarkupNamed("telegram")
	ev := func(kind string, d map[string]any) replies.Event { return replies.Event{Type: kind, Data: d} }
	for _, c := range []struct {
		m    replies.Markup
		e    replies.Event
		pres string
		want string
	}{
		{slack, ev("task.completed", map[string]any{"result": "", "final_response": "hi"}), replies.Concise, "hi"},
		{slack, ev("task.failed", map[string]any{"error": "boom"}), replies.Concise, ":x: *Failed* — boom"},
		// error: null reads as missing, as a reply that says "None" is no answer.
		{slack, ev("task.failed", map[string]any{"error": nil}), replies.Concise, ":x: *Failed* — Unknown error"},
		{slack, ev("approval.decided", map[string]any{"approved": false, "comment": "no"}), replies.Concise, ":no_entry_sign: *Denied* — no"},
		{slack, ev("tool.call", map[string]any{"tool_name": "shell"}), replies.Concise, ":wrench: Using _shell_..."},
		{slack, ev("tool.call", map[string]any{"tool_name": "shell"}), replies.Verbose, ":information_source: tool.call"},
		{tg, ev("task.completed", map[string]any{"result": "1.5 (ok)!"}), replies.Concise, `1\.5 \(ok\)\!`},
	} {
		if got := replies.FormatEvent(c.m, c.e, c.pres); got != c.want {
			t.Errorf("%s %v = %q want %q", c.e.Type, c.e.Data, got, c.want)
		}
	}
	if _, err := replies.MarkupNamed("html"); !replies.IsFatal(err) {
		t.Fatalf("unknown markup = %v", err)
	}
}

func TestLimitedNeverEndsOnALoneEscape(t *testing.T) {
	tg, _ := replies.MarkupNamed("telegram")
	suffix := "\n\n_\\(truncated\\)_"
	limit := len([]rune(suffix)) + 4
	got := replies.Limited(tg, `abc\.defghijklmnopqrstuvwxyz`, intp(limit))
	if got != "abc"+suffix {
		t.Fatalf("cut = %q", got)
	}
	got = replies.Limited(tg, `ab\\cdefghijklmnopqrstuvwxyz`, intp(limit))
	if got != `ab\\`+suffix {
		t.Fatalf("an escaped backslash was split: %q", got)
	}
	plain, _ := replies.MarkupNamed("plain")
	if got := replies.Limited(plain, "short", intp(100)); got != "short" {
		t.Fatalf("uncut = %q", got)
	}
	if got := replies.Limited(plain, "abcdefghijklmnopqrstuvwxyz", intp(20)); got != "abcdefg\n\n(truncated)" {
		t.Fatalf("plain cut = %q", got)
	}
}

func TestTaskWebhookBody(t *testing.T) {
	body, err := replies.TaskWebhookBody(replies.Event{Type: "task.completed", ID: "ev1", TaskID: "t1", Timestamp: "2026-11-15T10:00:00",
		Data: map[string]any{"agent_id": "a1", "result": "done <ok>", "total_cost": "0.1", "tokens_used": 12, "app_metadata": map[string]any{"k": "v"}}})
	if err != nil {
		t.Fatal(err)
	}
	want := `{"version":"1","type":"task.completed","event_id":"ev1","task_id":"t1","agent_id":"a1","execution_id":null,` +
		`"status":"completed","execution_status":null,"end_user_id":null,"metadata":{"k":"v"},"total_cost":"0.1","tokens_used":12,` +
		`"result":"done <ok>","error":null,"failure_reason":null,"timestamp":"2026-11-15T10:00:00"}`
	if string(body) != want {
		t.Fatalf("body =\n%s\nwant\n%s", body, want)
	}
	if body, _ := replies.TaskWebhookBody(replies.Event{Type: "tool.call"}); body != nil {
		t.Fatalf("a non-terminal event has a body: %s", body)
	}
}

type hook struct {
	mu      sync.Mutex
	status  int
	headers []http.Header
	bodies  []string
}

func (h *hook) server(t *testing.T) *httptest.Server {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		h.mu.Lock()
		h.headers = append(h.headers, r.Header.Clone())
		h.bodies = append(h.bodies, string(b))
		status := h.status
		h.mu.Unlock()
		if status == 0 {
			status = http.StatusNoContent
		}
		w.WriteHeader(status)
	}))
	t.Cleanup(srv.Close)
	return srv
}

func webhookSend(url string, signed bool) replies.Send {
	return replies.Send{
		Event:  replies.Event{Type: "task.completed", ID: "ev1", TaskID: "t1"},
		Target: replies.Target{Key: replies.TaskWebhookTarget, Config: map[string]any{"url": url, "signed": signed}},
	}
}

func TestTaskWebhookSignsAndPosts(t *testing.T) {
	h := &hook{}
	srv := h.server(t)
	at := time.Unix(1_700_000_000, 0)
	var asked string
	w := replies.TaskWebhook{Client: srv.Client(), Now: func() time.Time { return at },
		Secret: func(_ context.Context, _ scope.Workspace, owner, name string) (string, bool, error) {
			asked = owner + "/" + name
			return "s3cret", true, nil
		}}
	s := webhookSend(srv.URL, true)
	s.Owner = "u1"
	if err := w.Send(context.Background(), s, `{"a":1}`); err != nil {
		t.Fatal(err)
	}
	got := h.headers[0]
	if asked != "u1/task_webhook:t1" || got.Get(replies.SignatureHeader) != replies.Sign("s3cret", []byte(`{"a":1}`), at.Unix()) ||
		got.Get(replies.EventHeader) != "task.completed" || got.Get(replies.DeliveryHeader) != "ev1" || h.bodies[0] != `{"a":1}` {
		t.Fatalf("asked %s headers %v body %q", asked, got, h.bodies[0])
	}
	if sig := replies.Sign("k", []byte("b"), 5); !strings.HasPrefix(sig, "t=5,v1=") || len(sig) != len("t=5,v1=")+64 {
		t.Fatalf("signature = %q", sig)
	}
}

func TestTaskWebhookAnswers(t *testing.T) {
	h := &hook{}
	srv := h.server(t)
	w := replies.TaskWebhook{Client: srv.Client(), Secret: func(context.Context, scope.Workspace, string, string) (string, bool, error) {
		return "", false, nil
	}}
	ctx := context.Background()
	if err := w.Send(ctx, webhookSend(srv.URL, true), "{}"); err == nil || replies.IsFatal(err) || len(h.bodies) != 0 {
		t.Fatalf("a signed webhook without its secret yet = %v, posted %d", err, len(h.bodies))
	}
	if err := w.Send(ctx, webhookSend(srv.URL, false), "{}"); err != nil || h.headers[0].Get(replies.SignatureHeader) != "" {
		t.Fatalf("unsigned = %v %v", err, h.headers)
	}
	for status, fatal := range map[int]bool{500: false, 429: false, 404: true} {
		h.status = status
		err := w.Send(ctx, webhookSend(srv.URL, false), "{}")
		if err == nil || replies.IsFatal(err) != fatal {
			t.Errorf("%d = %v", status, err)
		}
	}
	if err := w.Send(ctx, webhookSend(srv.URL, false), ""); err != nil {
		t.Fatalf("no body = %v", err)
	}
}

func creds(m map[string]string) replies.Credentials {
	return func(context.Context, scope.Workspace, string, string, string) (map[string]string, error) {
		return m, nil
	}
}

func TestHTTPReplyRendersTheCatalogRequest(t *testing.T) {
	type call struct {
		auth string
		body map[string]any
	}
	var got []call
	answer := `{"ok":true}`
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var b map[string]any
		_ = json.NewDecoder(r.Body).Decode(&b)
		got = append(got, call{auth: r.Header.Get("Authorization"), body: b})
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, answer)
	}))
	t.Cleanup(srv.Close)
	reply := &domain.Reply{Markup: "slack", Limit: intp(1000), PermanentErrors: []string{"channel_not_found"}, Request: &domain.Request{
		Method: "POST", URL: srv.URL + "/chat.postMessage", Headers: map[string]string{"Authorization": "Bearer {credentials:bot_token}"},
		JSON: map[string]any{"channel": "{target:channel}", "text": "{message}"},
	}}
	h := replies.HTTPReply{Credentials: creds(map[string]string{"bot_token": "xoxb-1"}), Client: srv.Client()}
	s := replies.Send{
		Event: replies.Event{Type: "task.completed", Data: map[string]any{"result": "hello"}},
		Target: replies.Target{Key: replies.AddressTarget, Presentation: replies.Concise, Config: map[string]any{
			"type": "slack", "credential_type": "slack", "credential_key": "k1", "target": map[string]any{"channel": "C1"}}},
		Reply: reply,
	}
	msg, err := h.Format(s)
	if err != nil || msg != "hello" {
		t.Fatalf("format = %q %v", msg, err)
	}
	if err := h.Send(context.Background(), s, msg); err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got[0].auth != "Bearer xoxb-1" || got[0].body["channel"] != "C1" || got[0].body["text"] != "hello" {
		t.Fatalf("calls = %+v", got)
	}
	answer = `{"ok":false,"error":"channel_not_found"}`
	if err := h.Send(context.Background(), s, msg); !replies.IsFatal(err) {
		t.Fatalf("a permanent error = %v", err)
	}
	answer = `{"ok":false,"error":"ratelimited"}`
	if err := h.Send(context.Background(), s, msg); err == nil || replies.IsFatal(err) {
		t.Fatalf("a 2xx refusal = %v", err)
	}
}

func TestRaiseForReply(t *testing.T) {
	resp := func(status int, ctype, body string) *http.Response {
		return &http.Response{StatusCode: status, Header: http.Header{"Content-Type": {ctype}}, Body: io.NopCloser(strings.NewReader(body))}
	}
	for _, c := range []struct {
		r         *http.Response
		ok, fatal bool
		name      string
	}{
		{resp(200, "text/plain", "ok"), true, false, "plain 200"},
		{resp(200, "application/json", `{"ok":true}`), true, false, "json ok"},
		{resp(429, "text/plain", "slow"), false, false, "429"},
		{resp(502, "text/plain", "down"), false, false, "502"},
		{resp(403, "text/plain", "no"), false, true, "403"},
	} {
		err := replies.RaiseForReply(c.r, nil)
		if (err == nil) != c.ok || (err != nil && replies.IsFatal(err) != c.fatal) {
			t.Errorf("%s = %v", c.name, err)
		}
	}
}

func TestTelegramLiveSendsThenEditsThenForgets(t *testing.T) {
	mr := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	t.Cleanup(func() { _ = rdb.Close() })
	type call struct {
		method  string
		payload map[string]any
	}
	var calls []call
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var p map[string]any
		_ = json.NewDecoder(r.Body).Decode(&p)
		method := r.URL.Path[strings.LastIndex(r.URL.Path, "/")+1:]
		calls = append(calls, call{method: method, payload: p})
		if !strings.HasPrefix(r.URL.Path, "/botTOKEN/") {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		if method == "editMessageText" && len(calls) == 2 {
			w.WriteHeader(http.StatusBadRequest)
			_, _ = io.WriteString(w, `{"ok":false,"description":"Bad Request: message is not modified"}`)
			return
		}
		_, _ = io.WriteString(w, `{"ok":true,"result":{"message_id":77}}`)
	}))
	t.Cleanup(srv.Close)
	tg := replies.TelegramLive{Credentials: creds(map[string]string{"bot_token": "TOKEN"}), Redis: rdb, Client: srv.Client(), API: srv.URL}
	send := func(kind, msg string) error {
		return tg.Send(context.Background(), replies.Send{
			Event: replies.Event{Type: kind, TaskID: "t1"}, Reply: &domain.Reply{Markup: "telegram"},
			Target: replies.Target{Config: map[string]any{"credential_type": "telegram", "credential_key": "k",
				"target": map[string]any{"chat_id": 5, "message_id": 9}}},
		}, msg)
	}
	ctx := context.Background()
	if err := send("task.started", "Working"); err != nil {
		t.Fatal(err)
	}
	if id, _ := rdb.HGet(ctx, "tg:live:t1", "message_id").Result(); id != "77" {
		t.Fatalf("live message id = %q", id)
	}
	if err := send("tool.call", "Working"); err != nil {
		t.Fatalf("not modified = %v", err)
	}
	if err := send("tool.call", "Using shell"); err != nil {
		t.Fatal(err)
	}
	if err := send("task.completed", "Answer"); err != nil {
		t.Fatal(err)
	}
	if n, _ := rdb.Exists(ctx, "tg:live:t1").Result(); n != 0 {
		t.Fatal("the live message state outlived the task")
	}
	if len(calls) != 4 || calls[0].method != "sendMessage" || calls[0].payload["reply_to_message_id"] != float64(9) ||
		calls[2].method != "editMessageText" || calls[2].payload["text"] != "Working\nUsing shell" || calls[2].payload["message_id"] != float64(77) ||
		calls[3].payload["text"] != "Answer" {
		t.Fatalf("calls = %+v", calls)
	}
}

type smtpServer struct {
	mu       sync.Mutex
	authCode string
	lines    []string
	data     string
}

func (s *smtpServer) serve(t *testing.T) string {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = ln.Close() })
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go s.session(c)
		}
	}()
	return ln.Addr().String()
}

func (s *smtpServer) session(c net.Conn) {
	defer func() { _ = c.Close() }()
	r := bufio.NewReader(c)
	say := func(line string) { _, _ = io.WriteString(c, line+"\r\n") }
	say("220 test ESMTP")
	for {
		line, err := r.ReadString('\n')
		if err != nil {
			return
		}
		line = strings.TrimRight(line, "\r\n")
		s.mu.Lock()
		s.lines = append(s.lines, line)
		code := s.authCode
		s.mu.Unlock()
		switch cmd := strings.ToUpper(strings.SplitN(line, " ", 2)[0]); cmd {
		case "EHLO":
			say("250-test")
			say("250 AUTH PLAIN")
		case "AUTH":
			if code == "" {
				code = "235 ok"
			}
			say(code)
		case "MAIL", "RCPT":
			say("250 ok")
		case "DATA":
			say("354 go")
			var b strings.Builder
			for {
				l, err := r.ReadString('\n')
				if err != nil || l == ".\r\n" {
					break
				}
				b.WriteString(l)
			}
			s.mu.Lock()
			s.data = b.String()
			s.mu.Unlock()
			say("250 queued")
		case "QUIT":
			say("221 bye")
			return
		default:
			say("502 unknown")
		}
	}
}

func emailSend(port string) replies.Send {
	return replies.Send{
		Event: replies.Event{Type: "task.completed", Data: map[string]any{"result": "Report <ready>"}},
		Target: replies.Target{Config: map[string]any{"credential_type": "email", "credential_key": "k", "target": map[string]any{
			"to": "Ann <ann@example.test>", "subject": "Weekly", "message_id": "<m1@x>", "references": "<m0@x>"}}},
		Reply: &domain.Reply{Markup: "plain"},
	}
}

func TestEmailRepliesInThread(t *testing.T) {
	srv := &smtpServer{}
	host, port, _ := net.SplitHostPort(srv.serve(t))
	m := replies.Email{Dialer: &net.Dialer{}, Credentials: creds(map[string]string{
		"smtp_host": host, "smtp_port": port, "username": "bot", "password": "pw", "from_address": "bot@example.test"})}
	s := emailSend(port)
	msg, err := m.Format(s)
	if err != nil || !strings.Contains(msg, "Report &lt;ready&gt;") {
		t.Fatalf("format = %q %v", msg, err)
	}
	if err := m.Send(context.Background(), s, msg); err != nil {
		t.Fatal(err)
	}
	joined := strings.Join(srv.lines, "\n")
	for _, want := range []string{"AUTH PLAIN", "MAIL FROM:<bot@example.test>", "RCPT TO:<ann@example.test>"} {
		if !strings.Contains(joined, want) {
			t.Fatalf("session lacks %q:\n%s", want, joined)
		}
	}
	for _, want := range []string{"Subject: Re: Weekly", "In-Reply-To: <m1@x>", "References: <m0@x> <m1@x>", "Report <ready>"} {
		if !strings.Contains(srv.data, want) {
			t.Fatalf("mail lacks %q:\n%s", want, srv.data)
		}
	}
	srv.authCode = "535 bad credentials"
	if err := m.Send(context.Background(), s, msg); !replies.IsFatal(err) {
		t.Fatalf("a refused login = %v", err)
	}
}

// A port that is no number is final: retrying cannot make it one (email.py int() raised ValueError, retried).
func TestEmailPortThatIsNoNumberIsFatal(t *testing.T) {
	m := replies.Email{Dialer: &net.Dialer{}, Credentials: creds(map[string]string{"smtp_host": "127.0.0.1", "smtp_port": "smtp"})}
	if err := m.Send(context.Background(), emailSend(""), "<p>x</p>"); !replies.IsFatal(err) {
		t.Fatalf("err = %v", err)
	}
}

func TestReplyHeaders(t *testing.T) {
	if got := replies.ReplySubject("re: Hi"); got != "re: Hi" {
		t.Fatal(got)
	}
	if got := replies.ReplySubject("  a\n b "); got != "Re: a b" {
		t.Fatal(got)
	}
	if got := replies.ReplyAddress("Bob <bob@x.test>, c@y.test"); got != "bob@x.test" {
		t.Fatal(got)
	}
	if got := replies.ReplyReferences([]any{"<a>", "<b>"}, "<b>"); len(got) != 2 {
		t.Fatal(got)
	}
	if _, err := replies.BuildReply("a@x", "b@y\r\nBcc: c@z", "s", "", nil, "m"); !replies.IsFatal(err) {
		t.Fatalf("a header injection = %v", err)
	}
}

func TestTelegramLiveIgnoresProgressAfterTheEndAndSerializesSends(t *testing.T) {
	mr := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	t.Cleanup(func() { _ = rdb.Close() })
	var mu sync.Mutex
	var methods []string
	inflight, overlapped := 0, false
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		inflight++
		overlapped = overlapped || inflight > 1
		methods = append(methods, r.URL.Path[strings.LastIndex(r.URL.Path, "/")+1:])
		mu.Unlock()
		time.Sleep(30 * time.Millisecond)
		mu.Lock()
		inflight--
		mu.Unlock()
		_, _ = io.WriteString(w, `{"ok":true,"result":{"message_id":77}}`)
	}))
	t.Cleanup(srv.Close)
	tg := replies.TelegramLive{Credentials: creds(map[string]string{"bot_token": "TOKEN"}), Redis: rdb, Client: srv.Client(), API: srv.URL}
	send := func(kind, msg string) error {
		return tg.Send(context.Background(), replies.Send{
			Event: replies.Event{Type: kind, TaskID: "t1"}, Reply: &domain.Reply{Markup: "telegram"},
			Target: replies.Target{Config: map[string]any{"credential_type": "telegram", "credential_key": "k",
				"target": map[string]any{"chat_id": 5}}},
		}, msg)
	}
	var wg sync.WaitGroup
	for _, kind := range []string{"task.started", "tool.call", "tool.call"} {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if err := send(kind, "Working "+kind); err != nil {
				t.Error(err)
			}
		}()
	}
	wg.Wait()
	if overlapped {
		t.Fatal("two sends of one task ran at once")
	}
	if err := send("task.completed", "Answer"); err != nil {
		t.Fatal(err)
	}
	before := len(methods)
	if err := send("tool.call", "late retry"); err != nil {
		t.Fatal(err)
	}
	if len(methods) != before {
		t.Fatalf("a progress update after the end called Telegram: %v", methods[before:])
	}
	if n := strings.Count(strings.Join(methods, ","), "sendMessage"); n != 1 {
		t.Fatalf("%d messages posted: %v", n, methods)
	}
}
