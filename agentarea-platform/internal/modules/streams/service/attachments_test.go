package service_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store/storetest"
)

// botFiles is the Bot API's getFile and file download: file F1 is a video, BIG is over the
// download limit, GONE was deleted.
type botFiles struct {
	mu        sync.Mutex
	downloads int
}

func (b *botFiles) serve(w http.ResponseWriter, r *http.Request) {
	switch {
	case r.URL.Path == "/botTOKEN/getFile" && r.URL.Query().Get("file_id") == "F1":
		_, _ = w.Write([]byte(`{"ok":true,"result":{"file_id":"F1","file_path":"videos/file_7.MOV"}}`))
	case r.URL.Path == "/botTOKEN/getFile" && r.URL.Query().Get("file_id") == "PHOTO":
		_, _ = w.Write([]byte(`{"ok":true,"result":{"file_id":"PHOTO","file_path":"photos/file_9.jpg"}}`))
	case r.URL.Path == "/botTOKEN/getFile" && r.URL.Query().Get("file_id") == "BIG":
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte(`{"ok":false,"error_code":400,"description":"Bad Request: file is too big"}`))
	case r.URL.Path == "/botTOKEN/getFile":
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte(`{"ok":false,"error_code":400,"description":"Bad Request: invalid file_id"}`))
	case r.URL.Path == "/file/botTOKEN/videos/file_7.MOV":
		b.mu.Lock()
		b.downloads++
		b.mu.Unlock()
		_, _ = w.Write([]byte("movie bytes"))
	case r.URL.Path == "/file/botTOKEN/photos/file_9.jpg":
		_, _ = w.Write([]byte("jpeg bytes"))
	default:
		http.NotFound(w, r)
	}
}

type filesRig struct {
	*fireRig
	blob    *storetest.Blob
	bot     *botFiles
	stream  string
	source  string
	trigger domain.Trigger
}

func newFilesRig(t *testing.T) *filesRig {
	t.Helper()
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	ctx, _ := storetest.Caller(context.Background(), ws, "u1")
	bot := &botFiles{}
	api := httptest.NewServer(http.HandlerFunc(bot.serve))
	t.Cleanup(api.Close)
	g := &fireRig{ctx: ctx, ws: ws, tasks: &storetest.Tasks{}, firing: &storetest.FiringTasks{}, agent: uuid.NewString(), turns: turnLog{}}
	g.known = map[string]bool{g.agent: true}
	secrets := storetest.NewSecrets()
	r := &filesRig{fireRig: g, blob: &storetest.Blob{}, bot: bot}
	g.svc = service.New(service.Deps{
		DB: storetest.DB{Pool: pool}, Graph: &storetest.Graph{AllowAll: true}, Agents: storetest.Agents{Known: g.known},
		Schedules: &storetest.Schedules{}, TriggerQueue: "trigger-schedules", Tasks: g.tasks, Turns: g.turns, FiringTasks: g.firing,
		Broker: &storetest.Broker{}, Settings: service.DefaultSettings(), SourceTypes: storetest.ShippedSourceTypes(t),
		Secrets: secrets, SecretCatalog: secrets.Catalog, Blob: r.blob, Bus: &storetest.Bus{}, Dedup: &storetest.Dedup{},
		Quota: &storetest.Quota{}, Out: &telegramServer{}, APIURL: "https://api.example.test",
		Fetchers: map[string]service.AttachmentFetcher{"telegram.getFile": service.TelegramFiles{Client: api.Client(), API: api.URL}},
	})
	st, err := g.svc.CreateStream(ctx, "tg-"+uuid.NewString()[:8], "")
	if err != nil {
		t.Fatal(err)
	}
	src, _, err := g.svc.AddSource(ctx, st.ID, service.NewSource{SourceType: "telegram", Kind: "webhook",
		Credentials: map[string]service.Credential{"bot_token": value("TOKEN")}})
	if err != nil {
		t.Fatal(err)
	}
	n := cronNew(g.agent, true)
	if r.trigger, err = g.svc.Create(ctx, n); err != nil {
		t.Fatal(err)
	}
	r.stream, r.source = st.ID, src.ID
	return r
}

func ptrTo[T any](v T) *T { return &v }

func (r *filesRig) event(files ...domain.Attachment) domain.Event {
	return domain.Event{ID: uuid.NewString(), StreamID: r.stream, WorkspaceID: r.ws.ID(), SourceID: &r.source,
		SourceType: ptrTo("telegram"), Attachments: files}
}

func telegramFile(name, fileID string, size int64) domain.Attachment {
	return domain.Attachment{Name: name, Size: &size,
		Ref: `{"fetch":"telegram.getFile","item":{"file_id":"` + fileID + `","file_name":"` + name + `"}}`}
}

func (r *filesRig) fire(t *testing.T, e domain.Event) {
	t.Helper()
	data := map[string]any{"text": service.FilesLine(e.Attachments)}
	f, err := r.svc.Fire(r.ctx, r.ws, service.FireRequest{TriggerID: r.trigger.ID, Data: data, StreamEvent: &e,
		Event: &service.TriggerEvent{Conversation: true, Data: data}, RaiseRetryable: true})
	if err != nil || f.Outcome != service.OutcomeReacted {
		t.Fatalf("firing %+v %v", f, err)
	}
}

func TestAFileOnlyMessageGivesItsTaskTheFile(t *testing.T) {
	r := newFilesRig(t)
	e := r.event(telegramFile("IMG_6110.MOV", "F1", 11), telegramFile("file", "PHOTO", 10))
	r.fire(t, e)
	reqs := r.tasks.Submitted()
	if len(reqs) != 1 || !strings.HasSuffix(reqs[0].Description, "## Message\n\n(files: IMG_6110.MOV, file)") {
		t.Fatalf("a message with only files says a line naming them: %+v", reqs)
	}
	got := reqs[0].Attachments
	if len(got) != 2 || got[0].Name != "IMG_6110.MOV" || got[0].Size != 11 || got[0].ContentType != "video/quicktime" ||
		!strings.HasPrefix(got[0].Key, "events/"+r.stream+"/"+e.ID+"/") || got[0].SHA256 == "" {
		t.Fatalf("attachments %+v", got)
	}
	if got[1].Name != "file_9.jpg" || got[1].ContentType != "image/jpeg" {
		t.Fatalf("a file the event did not name takes the name its source gives: %+v", got[1])
	}
	if string(r.blob.Objects["workspaces/"+r.ws.ID()+"/"+got[0].Key]) != "movie bytes" {
		t.Fatalf("stored %v", r.blob.Keys())
	}

	r.fire(t, e)
	if r.bot.downloads != 1 {
		t.Fatalf("a retried firing fetched the file again: %d downloads", r.bot.downloads)
	}
	if again := r.tasks.Submitted()[1].Attachments; len(again) != 2 || again[0] != got[0] || again[1].Name != "file_9.jpg" {
		t.Fatalf("retry attachments %+v", again)
	}
}

func TestAFileTooLargeToFetchIsNamedToTheTask(t *testing.T) {
	r := newFilesRig(t)
	r.fire(t, r.event(telegramFile("LONG.MOV", "F1", 25<<20), telegramFile("BIG.MOV", "BIG", 0), telegramFile("GONE.MOV", "GONE", 0)))
	req := r.tasks.Submitted()[0]
	if len(req.Attachments) != 0 || r.bot.downloads != 0 {
		t.Fatalf("attached %+v after %d downloads", req.Attachments, r.bot.downloads)
	}
	for _, want := range []string{
		"The file LONG.MOV (25.0 MB) was not attached: Telegram files over 20.0 MB cannot be fetched.",
		"The file BIG.MOV was not attached: Telegram files over 20.0 MB cannot be fetched.",
		"The file GONE.MOV was not attached: Telegram refused the file (400): Bad Request: invalid file_id.",
	} {
		if !strings.Contains(req.Description, want) {
			t.Fatalf("the task is not told %q:\n%s", want, req.Description)
		}
	}
}

func TestFilesLineNamesTheFiles(t *testing.T) {
	for _, c := range []struct {
		files []domain.Attachment
		want  string
	}{
		{[]domain.Attachment{{Name: "IMG_6110.MOV"}}, "(file: IMG_6110.MOV)"},
		{[]domain.Attachment{{Name: "file"}}, "(file)"},
		{[]domain.Attachment{{Name: "a.pdf"}, {Name: ""}}, "(files: a.pdf, file)"},
	} {
		if got := service.FilesLine(c.files); got != c.want {
			t.Errorf("%v: %q", c.files, got)
		}
	}
}
