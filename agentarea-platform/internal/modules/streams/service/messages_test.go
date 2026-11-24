package service_test

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime"
	"mime/multipart"
	"net"
	"net/http"
	"strings"
	"sync"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store/storetest"
)

// telegramServer is the Bot API as a transport: it records each sendMessage and refuses chat 666
// the way Telegram refuses a user who never started the bot.
type telegramServer struct {
	mu   sync.Mutex
	sent []string
}

func (s *telegramServer) RoundTrip(r *http.Request) (*http.Response, error) {
	answer, status := `{"ok":true,"result":true}`, http.StatusOK
	token, method, _ := strings.Cut(strings.TrimPrefix(r.URL.Path, "/bot"), "/")
	if ct, params, _ := mime.ParseMediaType(r.Header.Get("Content-Type")); ct == "multipart/form-data" {
		form, err := multipart.NewReader(r.Body, params["boundary"]).ReadForm(1 << 20)
		if err != nil {
			return nil, err
		}
		for field, fhs := range form.File {
			f, _ := fhs[0].Open()
			body, _ := io.ReadAll(f)
			s.mu.Lock()
			s.sent = append(s.sent, fmt.Sprintf("%s %s %s %s=%s:%s", token, method, form.Value["chat_id"][0], field, fhs[0].Filename, body))
			s.mu.Unlock()
		}
	}
	if r.URL.Host == "api.telegram.org" && method == "sendMessage" {
		var m struct {
			ChatID any    `json:"chat_id"`
			Text   string `json:"text"`
		}
		if err := json.NewDecoder(r.Body).Decode(&m); err != nil {
			return nil, err
		}
		answer = `{"ok":true,"result":{"message_id":77}}`
		if m.ChatID == "666" {
			answer, status = `{"ok":false,"error_code":403,"description":"Forbidden: bot can't initiate conversation with a user"}`, http.StatusForbidden
		}
		s.mu.Lock()
		s.sent = append(s.sent, fmt.Sprintf("%s %v %s", token, m.ChatID, m.Text))
		s.mu.Unlock()
	}
	return &http.Response{StatusCode: status, Header: http.Header{"Content-Type": {"application/json"}},
		Body: io.NopCloser(strings.NewReader(answer)), Request: r}, nil
}

func (s *telegramServer) Transport(netguard.Destination) http.RoundTripper { return s }
func (s *telegramServer) Dialer() netguard.Dialer                          { return &net.Dialer{} }

func (s *telegramServer) take() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := s.sent
	s.sent = nil
	return out
}

type messaging struct {
	svc   *service.Service
	ctx   context.Context
	tg    *telegramServer
	links *links
	graph *storetest.Graph
	files *sandboxFiles
}

// sandboxFiles is a run's live files by task and path.
type sandboxFiles struct {
	sandboxapi.TaskFiles
	files map[string]string
}

func (f *sandboxFiles) ReadFile(_ context.Context, _, taskID, p string, _ bool) (sandboxapi.Download, error) {
	if p == "outputs/huge.mp4" {
		return sandboxapi.Download{Body: io.NopCloser(strings.NewReader("")), Header: http.Header{"Content-Length": {"62914560"}}}, nil
	}
	data, ok := f.files[taskID+"/"+p]
	if !ok {
		return sandboxapi.Download{}, &sandboxapi.TaskFileError{Status: http.StatusNotFound, Detail: "File not found"}
	}
	return sandboxapi.Download{Body: io.NopCloser(strings.NewReader(data)), Header: http.Header{"Content-Type": {"application/octet-stream"}}}, nil
}

func newMessaging(t *testing.T) messaging {
	t.Helper()
	return newMessagingWith(t, func(*service.Deps) {})
}

func newMessagingWith(t *testing.T, with func(*service.Deps)) messaging {
	t.Helper()
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	ctx, _ := storetest.Caller(context.Background(), ws, "owner")
	secrets := storetest.NewSecrets()
	m := messaging{ctx: ctx, tg: &telegramServer{}, graph: &storetest.Graph{AllowAll: true},
		links: &links{accounts: map[string][]string{}}, files: &sandboxFiles{files: map[string]string{}}}
	deps := service.Deps{
		DB: storetest.DB{Pool: pool}, Graph: m.graph, SourceTypes: storetest.ShippedSourceTypes(t),
		Secrets: secrets, SecretCatalog: secrets.Catalog, Blob: &storetest.Blob{}, Bus: &storetest.Bus{},
		Dedup: &storetest.Dedup{}, Quota: &storetest.Quota{}, Out: m.tg, APIURL: "https://api.example.test",
		Links: m.links, Owners: owners{owner: "owner"}, Notices: &storetest.Dedup{}, TaskFiles: m.files,
	}
	with(&deps)
	m.svc = service.New(deps)
	return m
}

// stream adds a readable stream with one source of sourceType, whose bot token is token.
func (m messaging) stream(t *testing.T, name, sourceType, token string) string {
	t.Helper()
	st, err := m.svc.CreateStream(m.ctx, name, "")
	if err != nil {
		t.Fatal(err)
	}
	src := service.NewSource{SourceType: sourceType, Kind: "webhook"}
	if token != "" {
		src.Credentials = map[string]service.Credential{"bot_token": value(token)}
	}
	if _, _, err := m.svc.AddSource(m.ctx, st.ID, src); err != nil {
		t.Fatal(err)
	}
	m.tg.take()
	m.graph.Readable = append(m.graph.Readable, st.ID)
	return st.ID
}

func (m messaging) send(to, stream, text string) (api.MessageSent, error) {
	return m.svc.SendMessage(m.ctx, api.MessageSend{UserID: to, Recipient: to + "@example.com", Stream: stream, Text: text})
}

func TestAMessageGoesToTheLinkedAccountThroughTheOnlyMessengerStream(t *testing.T) {
	m := newMessaging(t)
	m.stream(t, "hooks-"+uuid.NewString()[:8], "generic_webhook", "")
	name := "tg-" + uuid.NewString()[:8]
	id := m.stream(t, name, "telegram", "TOKEN")
	m.links.accounts["owner"] = []string{"42", "41"}

	out, err := m.send("owner", "", "The CEO report is ready")
	if err != nil {
		t.Fatal(err)
	}
	if !out.Sent || out.To != "owner@example.com" || out.Stream.ID != id || out.Stream.Name != name ||
		out.Messenger != "telegram" || out.MessageID == nil || *out.MessageID != 77 || out.Truncated {
		t.Fatalf("sent %+v", out)
	}
	if sent := m.tg.take(); len(sent) != 1 || sent[0] != "TOKEN 42 The CEO report is ready" {
		t.Fatalf("telegram got %q", sent)
	}
}

func TestAMessageReachesOnlyAMemberWhoLinkedTheirAccount(t *testing.T) {
	m := newMessaging(t)
	name := "tg-" + uuid.NewString()[:8]
	m.stream(t, name, "telegram", "TOKEN")

	_, err := m.send("bob", "", "hello")
	if err == nil || !strings.Contains(err.Error(), "bob@example.com has not linked a Telegram account") ||
		!strings.Contains(err.Error(), name) {
		t.Fatalf("unlinked: %v", err)
	}
	if sent := m.tg.take(); len(sent) != 0 {
		t.Fatalf("telegram got %q", sent)
	}

	m.links.accounts["bob"] = []string{"666"}
	_, err = m.send("bob", "", "hello")
	if err == nil || !strings.Contains(err.Error(), "can't initiate conversation") || !strings.Contains(err.Error(), "press Start") {
		t.Fatalf("never started the bot: %v", err)
	}
}

func TestTheStreamIsPickedWhenSeveralReachTheMember(t *testing.T) {
	m := newMessaging(t)
	first, second := "tg-a-"+uuid.NewString()[:8], "tg-b-"+uuid.NewString()[:8]
	m.stream(t, first, "telegram", "FIRST")
	id := m.stream(t, second, "telegram", "SECOND")
	m.links.accounts["owner"] = []string{"42"}

	_, err := m.send("owner", "", "hello")
	if err == nil || !strings.Contains(err.Error(), first) || !strings.Contains(err.Error(), second) ||
		!strings.Contains(err.Error(), "stream") {
		t.Fatalf("ambiguous: %v", err)
	}
	if _, err := m.send("owner", second, "by name"); err != nil {
		t.Fatal(err)
	}
	if _, err := m.send("owner", id, "by id"); err != nil {
		t.Fatal(err)
	}
	if sent := m.tg.take(); len(sent) != 2 || sent[0] != "SECOND 42 by name" || sent[1] != "SECOND 42 by id" {
		t.Fatalf("telegram got %q", sent)
	}
}

func TestNoMessengerStreamIsSaidSo(t *testing.T) {
	m := newMessaging(t)
	hooks := "hooks-" + uuid.NewString()[:8]
	m.stream(t, hooks, "generic_webhook", "")
	m.links.accounts["owner"] = []string{"42"}

	if _, err := m.send("owner", "", "hello"); err == nil || !strings.Contains(err.Error(), "no messenger stream") {
		t.Fatalf("none: %v", err)
	}
	if _, err := m.send("owner", hooks, "hello"); err == nil || !strings.Contains(err.Error(), "has no Telegram source") {
		t.Fatalf("not a messenger: %v", err)
	}
	if sent := m.tg.take(); len(sent) != 0 {
		t.Fatalf("telegram got %q", sent)
	}
}

func TestAStreamTheCallerCannotReadIsNotUsed(t *testing.T) {
	m := newMessaging(t)
	name := "tg-" + uuid.NewString()[:8]
	m.stream(t, name, "telegram", "TOKEN")
	m.links.accounts["owner"] = []string{"42"}
	m.graph.AllowAll, m.graph.Readable = false, nil

	if _, err := m.send("owner", "", "hello"); err == nil || !strings.Contains(err.Error(), "no messenger stream") {
		t.Fatalf("unreadable picked: %v", err)
	}
	if _, err := m.send("owner", name, "hello"); err == nil {
		t.Fatal("an unreadable stream was used by name")
	}
	if sent := m.tg.take(); len(sent) != 0 {
		t.Fatalf("telegram got %q", sent)
	}
}

func TestAMessageCarriesTheRunsFiles(t *testing.T) {
	m := newMessaging(t)
	m.stream(t, "tg-"+uuid.NewString()[:8], "telegram", "TOKEN")
	m.links.accounts["owner"] = []string{"42"}
	m.files.files["task-1/outputs/clip.subtitled.mp4"] = "movie"
	m.files.files["task-1/outputs/clip.srt"] = "1"
	in := api.MessageSend{UserID: "owner", Recipient: "owner@example.com", Text: "Your video", TaskID: "task-1",
		Files: []string{"/workspace/outputs/clip.subtitled.mp4", "./outputs/clip.srt"}}

	out, err := m.svc.SendMessage(m.ctx, in)
	if err != nil {
		t.Fatal(err)
	}
	if len(out.Files) != 2 || out.Files[0] != "outputs/clip.subtitled.mp4" {
		t.Fatalf("sent %+v", out)
	}
	sent := m.tg.take()
	if len(sent) != 3 || sent[0] != "TOKEN 42 Your video" || sent[1] != "TOKEN sendVideo 42 video=clip.subtitled.mp4:movie" ||
		sent[2] != "TOKEN sendDocument 42 document=clip.srt:1" {
		t.Fatalf("telegram got %q", sent)
	}

	for _, c := range []struct {
		files      []string
		task, want string
	}{
		{[]string{"../etc/passwd"}, "task-1", "is not a path in the run's workspace"},
		{[]string{"outputs/missing.mp4"}, "task-1", "outputs/missing.mp4 cannot be read: File not found"},
		{[]string{"outputs/clip.srt"}, "", "files can be sent only from a run"},
		{[]string{"outputs/huge.mp4"}, "task-1", "outputs/huge.mp4 is larger than the 50 MB a Telegram bot sends"},
		{[]string{"a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k"}, "task-1", "at most 10 files go in one message, 11 given"},
	} {
		in.Files, in.TaskID = c.files, c.task
		if _, err := m.svc.SendMessage(m.ctx, in); err == nil || !strings.Contains(err.Error(), c.want) {
			t.Fatalf("%v: %v", c.files, err)
		}
	}
	if sent := m.tg.take(); len(sent) != 0 {
		t.Fatalf("a refused file sent %q", sent)
	}
}

func TestAFileTooLargeToSendIsLinkedToTheTask(t *testing.T) {
	m := newMessagingWith(t, func(d *service.Deps) { d.AppURL = "https://app.example.test/" })
	m.stream(t, "tg-"+uuid.NewString()[:8], "telegram", "TOKEN")
	m.links.accounts["owner"] = []string{"42"}
	m.files.files["task-1/outputs/clip.srt"] = "1"
	c, _ := authn.CallerFrom(m.ctx)
	out, err := m.svc.SendMessage(m.ctx, api.MessageSend{UserID: "owner", Recipient: "owner@example.com", TaskID: "task-1",
		Files: []string{"outputs/huge.mp4", "outputs/clip.srt"}})
	if err != nil {
		t.Fatal(err)
	}
	if len(out.Linked) != 1 || out.Linked[0] != "outputs/huge.mp4" || len(out.Files) != 1 {
		t.Fatalf("sent %+v", out)
	}
	link := "https://app.example.test/w/" + c.Workspace.Slug() + "/tasks/task-1/files?file=outputs%2Fhuge.mp4"
	sent := m.tg.take()
	if len(sent) != 2 || sent[0] != "TOKEN 42 huge.mp4 (60.0 MB): "+link || sent[1] != "TOKEN sendDocument 42 document=clip.srt:1" {
		t.Fatalf("telegram got %q", sent)
	}
}
