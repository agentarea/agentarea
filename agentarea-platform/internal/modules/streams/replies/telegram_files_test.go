package replies_test

import (
	"context"
	"encoding/json"
	"io"
	"mime"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"github.com/alicebob/miniredis/v2"
	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	identityapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/replies"
)

// publishedFiles is a task's published artifacts by id.
type publishedFiles struct {
	sandboxapi.TaskFiles
	list []sandboxapi.TaskArtifact
	data map[string]string
}

func (p *publishedFiles) Artifacts(context.Context, string, string) ([]sandboxapi.TaskArtifact, error) {
	return p.list, nil
}

func (p *publishedFiles) Artifact(_ context.Context, _, _, id string) (sandboxapi.Download, error) {
	return sandboxapi.Download{Body: io.NopCloser(strings.NewReader(p.data[id]))}, nil
}

func (p *publishedFiles) add(path, ct, data string, size int64) {
	id := "art_" + strings.ReplaceAll(uuid.NewString(), "-", "")
	if size == 0 {
		size = int64(len(data))
	}
	p.list = append(p.list, sandboxapi.TaskArtifact{ID: id, Path: path, Size: size, ContentType: ct, SHA256: "sha-" + data})
	p.data[id] = data
}

// botUploads is the Bot API: it records each call as "method field=name:content" or "method text",
// and refuses a video named broken.mp4 in every form.
type botUploads struct {
	mu    sync.Mutex
	calls []string
}

func (b *botUploads) serve(w http.ResponseWriter, r *http.Request) {
	method := r.URL.Path[strings.LastIndex(r.URL.Path, "/")+1:]
	call := method
	refuse, tooLarge := false, false
	if ct, params, _ := mime.ParseMediaType(r.Header.Get("Content-Type")); ct == "multipart/form-data" {
		mr := multipart.NewReader(r.Body, params["boundary"])
		for {
			part, err := mr.NextPart()
			if err != nil {
				break
			}
			if part.FileName() != "" {
				body, _ := io.ReadAll(part)
				call += " " + part.FormName() + "=" + part.FileName() + ":" + string(body)
				refuse = part.FileName() == "broken.mp4"
				tooLarge = part.FileName() == "huge.mp4"
			}
		}
	} else {
		body, _ := io.ReadAll(r.Body)
		if i := strings.Index(string(body), `"text":"`); i >= 0 {
			call += " " + strings.SplitN(string(body)[i+8:], `"`, 2)[0]
		}
	}
	b.mu.Lock()
	b.calls = append(b.calls, call)
	b.mu.Unlock()
	if tooLarge {
		w.WriteHeader(http.StatusRequestEntityTooLarge)
		_, _ = io.WriteString(w, `{"ok":false,"description":"Request Entity Too Large"}`)
		return
	}
	if refuse {
		w.WriteHeader(http.StatusBadRequest)
		_, _ = io.WriteString(w, `{"ok":false,"description":"Bad Request: wrong file"}`)
		return
	}
	_, _ = io.WriteString(w, `{"ok":true,"result":{"message_id":77}}`)
}

func (b *botUploads) take() []string {
	b.mu.Lock()
	defer b.mu.Unlock()
	out := b.calls
	b.calls = nil
	return out
}

func TestTheEndOfATurnSendsTheChatTheFilesItPublished(t *testing.T) {
	mr := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	t.Cleanup(func() { _ = rdb.Close() })
	bot := &botUploads{}
	srv := httptest.NewServer(http.HandlerFunc(bot.serve))
	t.Cleanup(srv.Close)
	files := &publishedFiles{data: map[string]string{}}
	files.add("outputs/IMG_6110.subtitled.mp4", "video/mp4", "movie", 0)
	files.add("outputs/IMG_6110.srt", "", "1\n00:00:00,000 --> 00:00:02,000\nHi", 0)
	files.add("outputs/raw.mp4", "video/mp4", "big", 60<<20)
	ws, _ := scope.NewWorkspace(uuid.NewString(), "")
	tg := replies.TelegramLive{Credentials: creds(map[string]string{"bot_token": "TOKEN"}), Redis: rdb, Client: srv.Client(), API: srv.URL, Files: files}
	send := func(kind, at, msg string) {
		t.Helper()
		if err := tg.Send(context.Background(), replies.Send{
			Event: replies.Event{Type: kind, TaskID: "t1", Timestamp: at}, Reply: &domain.Reply{Markup: "telegram"}, Workspace: ws,
			Target: replies.Target{Config: map[string]any{"credential_type": "telegram", "credential_key": "k",
				"target": map[string]any{"chat_id": 42, "message_id": 9}}},
		}, msg); err != nil {
			t.Fatal(err)
		}
	}
	send("task.started", "2026-11-24T10:00:00Z", "Working")
	send("task.completed", "2026-11-24T10:01:00Z", "Here is the video")
	got := bot.take()
	want := []string{
		"sendMessage Working",
		"editMessageText Here is the video",
		"sendVideo video=IMG_6110.subtitled.mp4:movie",
		"sendDocument document=IMG_6110.srt:1\n00:00:00,000 --> 00:00:02,000\nHi",
		"sendMessage raw.mp4 is 60.0 MB; a Telegram bot sends files up to 50 MB.",
	}
	if strings.Join(got, "|") != strings.Join(want, "|") {
		t.Fatalf("calls\n got %q\nwant %q", got, want)
	}

	files.add("outputs/broken.mp4", "video/mp4", "bad", 0)
	send("task.completed", "2026-11-24T10:05:00Z", "Again")
	got = bot.take()
	want = []string{
		"sendMessage Again",
		"sendVideo video=broken.mp4:bad",
		"sendDocument document=broken.mp4:bad",
		"sendMessage Could not send broken.mp4: Bad Request: wrong file",
	}
	if strings.Join(got, "|") != strings.Join(want, "|") {
		t.Fatalf("a later turn sends only its new files, a refused one is named\n got %q\nwant %q", got, want)
	}

	send("task.failed", "2026-11-24T10:09:00Z", "Failed")
	if got := bot.take(); len(got) != 1 || got[0] != "sendMessage Failed" {
		t.Fatalf("a failed turn sends no files: %q", got)
	}
}

type slugs map[string]string

func (s slugs) Slug(_ context.Context, id string) (string, error) {
	slug, ok := s[id]
	if !ok {
		return "", identityapi.ErrWorkspaceNotFound
	}
	return slug, nil
}

func TestTheAnswerLinksTheTaskPage(t *testing.T) {
	mr := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	t.Cleanup(func() { _ = rdb.Close() })
	var texts []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var p map[string]any
		_ = json.NewDecoder(r.Body).Decode(&p)
		text, _ := p["text"].(string)
		texts = append(texts, text)
		if strings.Contains(text, "(parse me)") && p["parse_mode"] != nil {
			w.WriteHeader(http.StatusBadRequest)
			_, _ = io.WriteString(w, `{"ok":false,"description":"Bad Request: can't parse entities"}`)
			return
		}
		_, _ = io.WriteString(w, `{"ok":true,"result":{"message_id":77}}`)
	}))
	t.Cleanup(srv.Close)
	ws, _ := scope.NewWorkspace(uuid.NewString(), "")
	tg := replies.TelegramLive{Credentials: creds(map[string]string{"bot_token": "TOKEN"}), Redis: rdb, Client: srv.Client(), API: srv.URL,
		AppURL: "https://app.example.test/", Slugs: slugs{ws.ID(): "acme"}}
	send := func(kind, task, msg string) {
		t.Helper()
		if err := tg.Send(context.Background(), replies.Send{
			Event: replies.Event{Type: kind, TaskID: task}, Reply: &domain.Reply{Markup: "telegram"}, Workspace: ws,
			Target: replies.Target{Config: map[string]any{"credential_type": "telegram", "credential_key": "k",
				"target": map[string]any{"chat_id": 42, "message_id": 9}}},
		}, msg); err != nil {
			t.Fatal(err)
		}
	}
	send("task.started", "t1", "Working")
	send("task.completed", "t1", "Done")
	if len(texts) != 2 || texts[0] != "Working" || texts[1] != "Done\n\n[Open in AgentArea](https://app.example.test/w/acme/tasks/t1)" {
		t.Fatalf("texts %q: only the end links the task", texts)
	}
	texts = nil
	send("task.completed", "t2", "(parse me)")
	if len(texts) != 2 || texts[1] != "(parse me)\n\nOpen in AgentArea: https://app.example.test/w/acme/tasks/t2" {
		t.Fatalf("a plain resend keeps the link readable: %q", texts)
	}
}

func TestAFileTooLargeForTheChatIsLinkedInTheWebapp(t *testing.T) {
	mr := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	t.Cleanup(func() { _ = rdb.Close() })
	bot := &botUploads{}
	srv := httptest.NewServer(http.HandlerFunc(bot.serve))
	t.Cleanup(srv.Close)
	files := &publishedFiles{data: map[string]string{}}
	files.add("outputs/raw.mp4", "video/mp4", "big", 60<<20)
	files.add("outputs/huge.mp4", "video/mp4", "refused", 30<<20)
	ws, _ := scope.NewWorkspace(uuid.NewString(), "")
	tg := replies.TelegramLive{Credentials: creds(map[string]string{"bot_token": "TOKEN"}), Redis: rdb, Client: srv.Client(), API: srv.URL,
		Files: files, AppURL: "https://app.example.test", Slugs: slugs{ws.ID(): "acme"}}
	if err := tg.Send(context.Background(), replies.Send{
		Event: replies.Event{Type: "task.completed", TaskID: "t1", Timestamp: "2026-11-24T10:01:00Z"}, Reply: &domain.Reply{Markup: "telegram"},
		Workspace: ws, Target: replies.Target{Config: map[string]any{"credential_type": "telegram", "credential_key": "k",
			"target": map[string]any{"chat_id": 42, "message_id": 9}}},
	}, "Done"); err != nil {
		t.Fatal(err)
	}
	got := bot.take()
	want := "sendMessage raw.mp4 (60.0 MB): https://app.example.test/w/acme/tasks/t1/files?file=outputs%2Fraw.mp4\\n" +
		"huge.mp4 (30.0 MB): https://app.example.test/w/acme/tasks/t1/files?file=outputs%2Fhuge.mp4"
	if len(got) != 3 || got[1] != "sendVideo video=huge.mp4:refused" || got[2] != want {
		t.Fatalf("calls %q\nwant last %q", got, want)
	}
}
