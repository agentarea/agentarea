package runner

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/coder/websocket"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/workflows"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

const (
	wsID       = "ws-1"
	wsSlug     = "acme"
	runnerKey  = "aa_runner"
	memberKey  = "aa_member"
	otherKey   = "aa_other"
	noRunKey   = "aa_harness"
	agentID    = "11111111-1111-4111-8111-111111111111"
	turnTaskID = "22222222-2222-4222-8222-222222222222"
	otherTask  = "33333333-3333-4333-8333-333333333333"
	subTask    = "44444444-4444-4444-8444-444444444444"
	parentTask = "55555555-5555-4555-8555-555555555555"
)

var clientID = uuid.NewSHA1(uuid.NameSpaceOID, []byte("client")).String()

type fakeGate struct{ keys map[string]authn.Principal }

func (g fakeGate) Authenticate(_ context.Context, r *http.Request) (authn.Principal, error) {
	token, ok := authn.BearerToken(r)
	p, found := g.keys[token]
	if !ok || !found {
		return authn.Principal{}, httpx.Unauthorized("Not authenticated")
	}
	return p, nil
}

func (g fakeGate) Caller(_ context.Context, p authn.Principal, route authn.Route) (authn.Caller, error) {
	if route.Binding == nil || route.Binding.ClientID != p.BoundClientID {
		return authn.Caller{}, httpx.Forbidden(authn.DetailRunnerKeyRefused)
	}
	ws, err := scope.NewWorkspace(route.Binding.WorkspaceID, route.Binding.WorkspaceSlug)
	return authn.Caller{Principal: p, Workspace: ws}, err
}

func (g fakeGate) RunnerKey(_ context.Context, token string) (*authn.Principal, error) {
	p, ok := g.keys[token]
	if !ok || p.BoundClientID == "" {
		return nil, nil
	}
	return &p, nil
}

func (g fakeGate) EnterAsRunner(p authn.Principal, ws scope.Workspace) (authn.Caller, error) {
	return authn.Caller{Principal: p, Workspace: ws}, nil
}

type fakeClients struct {
	mu      sync.Mutex
	clients map[string]agentsapi.RunnerClient
	models  []agentsapi.RunnerModel
	dflt    string
}

func (f *fakeClients) Client(_ context.Context, ws scope.Workspace, id string) (agentsapi.RunnerClient, bool, error) {
	c, ok := f.clients[id]
	if !ok || c.WorkspaceID != ws.ID() {
		return agentsapi.RunnerClient{}, false, nil
	}
	return c, true, nil
}

func (f *fakeClients) RecordHello(_ context.Context, _ scope.Workspace, _ string, models []agentsapi.RunnerModel, dflt string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.models, f.dflt = models, dflt
	return nil
}

func (f *fakeClients) Agent(_ context.Context, _ scope.Workspace, id string) (agentsapi.RunnerAgent, error) {
	if id != agentID {
		return agentsapi.RunnerAgent{}, agentsapi.ErrNotFound
	}
	return agentsapi.RunnerAgent{ReasoningEffort: "high", Instructions: "Be brief.\n\n## Skill: s\n\nbody"}, nil
}

type fakeSlugs struct{}

func (fakeSlugs) Slug(context.Context, string) (string, error) { return wsSlug, nil }

type notified struct {
	channel string
	fields  map[string]string
}

type fakeBroker struct {
	events.Broker
	notes      chan notified
	deliveries chan map[string]string
}

func (b *fakeBroker) Notify(_ context.Context, channel string, fields map[string]string) error {
	b.notes <- notified{channel, fields}
	return nil
}

func (b *fakeBroker) OpenLive(context.Context) (events.LiveChannels, error) {
	return &fakeLive{in: b.deliveries}, nil
}

type fakeLive struct {
	in      chan map[string]string
	channel string
}

func (l *fakeLive) Subscribe(_ context.Context, ch string) error { l.channel = ch; return nil }
func (l *fakeLive) Unsubscribe(context.Context, string) error    { return nil }
func (l *fakeLive) Close() error                                 { return nil }
func (l *fakeLive) Next(ctx context.Context, timeout time.Duration) (string, map[string]string, bool, error) {
	select {
	case f := <-l.in:
		return l.channel, f, true, nil
	case <-time.After(timeout):
		return "", nil, false, nil
	case <-ctx.Done():
		return "", nil, false, ctx.Err()
	}
}

type fakePresence struct{ marks chan string }

func (p fakePresence) Mark(_ context.Context, id string) error {
	select {
	case p.marks <- id:
	default:
	}
	return nil
}

type put struct {
	key, contentType string
	body             []byte
}

type fakeFiles struct {
	blob.Store
	mu   sync.Mutex
	puts []put
}

func (f *fakeFiles) Put(_ context.Context, key string, body io.Reader, _ int64, opts blob.PutOptions) error {
	b, err := io.ReadAll(body)
	f.mu.Lock()
	defer f.mu.Unlock()
	f.puts = append(f.puts, put{key, opts.ContentType, b})
	return err
}

type published struct {
	workspaceID, taskID, path, contentType string
	body                                   []byte
}

type fakeArtifacts struct {
	mu   sync.Mutex
	pubs []published
	err  error
}

func (f *fakeArtifacts) PublishArtifact(_ context.Context, workspaceID, taskID, p, contentType string, body []byte) (sandboxapi.TaskArtifact, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.err != nil {
		return sandboxapi.TaskArtifact{}, f.err
	}
	f.pubs = append(f.pubs, published{workspaceID, taskID, p, contentType, body})
	return sandboxapi.TaskArtifact{Path: p}, nil
}

// fakeShared is the durable workspace of the parent task a subtask works on.
type fakeShared struct {
	mu   sync.Mutex
	puts []string
	err  error
}

func (s *fakeShared) PutFiles(_ context.Context, _, taskID string, files []sandboxapi.WorkspaceFile, _ sandboxapi.WriteOptions) (sandboxapi.ManifestRef, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.err != nil {
		return sandboxapi.ManifestRef{}, s.err
	}
	for _, f := range files {
		s.puts = append(s.puts, taskID+":"+f.Path+"="+string(f.Data))
	}
	return sandboxapi.ManifestRef{}, nil
}

type fakeWorker struct {
	queue  string
	limits durable.Limits
}

func (fakeWorker) RegisterWorkflow(durable.Workflow)      {}
func (fakeWorker) RegisterActivity(durable.Activity)      {}
func (fakeWorker) Kinds() map[string]durable.ActivityKind { return nil }
func (fakeWorker) Run(ctx context.Context) error          { <-ctx.Done(); return nil }
func (fakeWorker) Polling() bool                          { return true }
func (w *fakeWorkers) Executor() durable.Executor         { return nil }
func (w *fakeWorkers) NewWorker(q string, l durable.Limits) durable.Worker {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.opened = append(w.opened, fakeWorker{q, l})
	return fakeWorker{q, l}
}

type fakeWorkers struct {
	mu     sync.Mutex
	opened []fakeWorker
}

type fakeTokens struct{ claims chan authn.TurnClaims }

func (t fakeTokens) Issue(c authn.TurnClaims, _ time.Duration) (string, error) {
	t.claims <- c
	return "turn-token", nil
}
func (fakeTokens) Decode(string) (authn.TurnClaims, bool) { return authn.TurnClaims{}, false }

type fakeLiveTurns struct {
	mu    sync.Mutex
	alive map[string]bool
}

func (l *fakeLiveTurns) set(id string, v bool) error {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.alive[id] = v
	return nil
}
func (l *fakeLiveTurns) Begin(_ context.Context, id string, _ time.Duration) error {
	return l.set(id, true)
}
func (l *fakeLiveTurns) Renew(_ context.Context, id string, _ time.Duration) error {
	return l.set(id, true)
}
func (l *fakeLiveTurns) End(_ context.Context, id string) error { return l.set(id, false) }
func (l *fakeLiveTurns) Alive(_ context.Context, id string) (bool, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.alive[id], nil
}

type fakeTasks struct {
	mu       sync.Mutex
	tasks    map[string]store.RunnerTask
	sessions map[string]string
	lost     map[string][]string
}

func (f *fakeTasks) NoteLostOutput(_ context.Context, _ scope.Workspace, id, note string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.lost[id] = append(f.lost[id], note)
	return nil
}

func (f *fakeTasks) TakeLostOutputs(_ context.Context, _ scope.Workspace, id string) ([]string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	out := f.lost[id]
	delete(f.lost, id)
	return out, nil
}

func (f *fakeTasks) Task(_ context.Context, _ scope.Workspace, id string) (store.RunnerTask, error) {
	t, ok := f.tasks[id]
	if !ok {
		return store.RunnerTask{}, store.ErrTaskNotFound
	}
	return t, nil
}

func (f *fakeTasks) KeepSession(_ context.Context, _ scope.Workspace, id, session string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.sessions[id] = session
	return nil
}

type rig struct {
	srv      *httptest.Server
	clients  *fakeClients
	broker   *fakeBroker
	files    *fakeFiles
	outputs  *fakeArtifacts
	shared   *fakeShared
	workers  *fakeWorkers
	tasks    *fakeTasks
	live     *fakeLiveTurns
	tokens   fakeTokens
	turns    chan workflows.RunnerTurns
	presence fakePresence
}

func newRig(t *testing.T) *rig {
	t.Helper()
	r := &rig{
		clients: &fakeClients{clients: map[string]agentsapi.RunnerClient{
			clientID: {ID: clientID, WorkspaceID: wsID, Kind: "codex", Runner: true, DefaultModel: "gpt-5",
				AllowDomains: []string{"example.com"}, Sandbox: true},
			"harness-client": {ID: "harness-client", WorkspaceID: wsID, Kind: "harness"},
		}},
		broker:   &fakeBroker{notes: make(chan notified, 64), deliveries: make(chan map[string]string, 4)},
		files:    &fakeFiles{},
		outputs:  &fakeArtifacts{},
		shared:   &fakeShared{},
		workers:  &fakeWorkers{},
		live:     &fakeLiveTurns{alive: map[string]bool{}},
		tokens:   fakeTokens{claims: make(chan authn.TurnClaims, 4)},
		turns:    make(chan workflows.RunnerTurns, 1),
		presence: fakePresence{marks: make(chan string, 64)},
		tasks: &fakeTasks{sessions: map[string]string{}, lost: map[string][]string{}, tasks: map[string]store.RunnerTask{
			turnTaskID: {ID: turnTaskID, AgentID: agentID, CreatedBy: "creator", SourceIdentity: "user:u1",
				Parameters: map[string]any{}, Metadata: map[string]any{runnerClientKey: clientID}},
			subTask: {ID: subTask, AgentID: agentID, CreatedBy: "creator", Parameters: map[string]any{}, Metadata: map[string]any{
				runnerClientKey: clientID, workspaceTaskKey: parentTask,
			}},
			otherTask: {ID: otherTask, AgentID: agentID, CreatedBy: "creator",
				Parameters: map[string]any{}, Metadata: map[string]any{runnerClientKey: "another"}},
		}},
	}
	gate := fakeGate{keys: map[string]authn.Principal{
		runnerKey: {UserID: "creator", BoundWorkspaceID: wsID, BoundClientID: clientID},
		memberKey: {UserID: "creator", BoundWorkspaceID: wsID},
		otherKey:  {UserID: "creator", BoundWorkspaceID: wsID, BoundClientID: uuid.NewString()},
		noRunKey:  {UserID: "creator", BoundWorkspaceID: wsID, BoundClientID: "harness-client"},
	}}
	log := slog.New(slog.DiscardHandler)
	errs := httpx.NewErrors("http://api", log)
	mux := chi.NewRouter()
	Mount(mux, errs, Deps{
		Tasks: r.tasks, Gate: gate, Clients: r.clients, Slugs: fakeSlugs{}, Broker: r.broker, Presence: r.presence,
		Files: r.files, Artifacts: r.outputs, Store: r.shared, FileStoreHost: "storage.example.com", Workers: r.workers, Tokens: r.tokens, Live: r.live, Log: log,
		register: func(_ durable.Worker, turns workflows.RunnerTurns, _ durable.Executor) { r.turns <- turns },
	})
	r.srv = httptest.NewServer(mux)
	t.Cleanup(r.srv.Close)
	return r
}

func (r *rig) do(t *testing.T, method, path, key string, body io.Reader) (int, string) {
	t.Helper()
	req, err := http.NewRequestWithContext(context.Background(), method, r.srv.URL+path, body)
	if err != nil {
		t.Fatal(err)
	}
	if key != "" {
		req.Header.Set("Authorization", "Bearer "+key)
	}
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = res.Body.Close() }()
	b, _ := io.ReadAll(res.Body)
	return res.StatusCode, string(b)
}

func TestWhoamiAdmitsOnlyTheClientsRunnerKey(t *testing.T) {
	r := newRig(t)
	status, body := r.do(t, http.MethodGet, "/v1/runner/whoami", runnerKey, nil)
	if status != http.StatusOK {
		t.Fatalf("whoami: %d %s", status, body)
	}
	var got map[string]string
	if err := json.Unmarshal([]byte(body), &got); err != nil {
		t.Fatal(err)
	}
	if got["client_id"] != clientID || got["workspace"] != wsSlug || got["kind"] != "codex" {
		t.Fatalf("whoami: %v", got)
	}
	for _, c := range []struct {
		key    string
		status int
		detail string
	}{
		{"", http.StatusUnauthorized, ""},
		{memberKey, http.StatusForbidden, detailOnlyRunnerKey},
		{otherKey, http.StatusNotFound, detailNoClient},
	} {
		status, body := r.do(t, http.MethodGet, "/v1/runner/whoami", c.key, nil)
		if status != c.status || !strings.Contains(body, c.detail) {
			t.Errorf("key %q: %d %s", c.key, status, body)
		}
	}
}

func TestUploadStoresTheFileInItsTaskFolder(t *testing.T) {
	r := newRig(t)
	status, body := r.do(t, http.MethodPut, "/v1/runner/tasks/"+turnTaskID+"/files/out/report%20one.txt", runnerKey, strings.NewReader("# hi"))
	if status != http.StatusNoContent {
		t.Fatalf("upload: %d %s", status, body)
	}
	if len(r.files.puts) != 1 {
		t.Fatalf("puts: %v", r.files.puts)
	}
	p := r.files.puts[0]
	if p.key != "harness-files/"+wsID+"/"+turnTaskID+"/out/report one.txt" || string(p.body) != "# hi" || p.contentType != "text/plain" {
		t.Fatalf("put: %+v", p)
	}
	for _, c := range []struct {
		name, path, key string
		status          int
		detail          string
	}{
		{"another client's task", "/v1/runner/tasks/" + otherTask + "/files/a.txt", runnerKey, http.StatusNotFound, detailNoTask},
		{"unknown task", "/v1/runner/tasks/" + uuid.NewString() + "/files/a.txt", runnerKey, http.StatusNotFound, detailNoTask},
		{"parent segment", "/v1/runner/tasks/" + turnTaskID + "/files/a/../../b", runnerKey, http.StatusUnprocessableEntity, detailRelative},
		{"bad task id", "/v1/runner/tasks/nope/files/a.txt", runnerKey, http.StatusUnprocessableEntity, "task_id"},
		{"member key", "/v1/runner/tasks/" + turnTaskID + "/files/a.txt", memberKey, http.StatusForbidden, detailOnlyRunnerKey},
	} {
		status, body := r.do(t, http.MethodPut, c.path, c.key, strings.NewReader("x"))
		if status != c.status || !strings.Contains(body, c.detail) {
			t.Errorf("%s: %d %s", c.name, status, body)
		}
	}
	status, body = r.do(t, http.MethodPut, "/v1/runner/tasks/"+turnTaskID+"/files/big.bin", runnerKey, bytes.NewReader(make([]byte, fileMaxBytes+1)))
	if status != http.StatusRequestEntityTooLarge || !strings.Contains(body, detailTooLarge) {
		t.Errorf("too large: %d %s", status, body)
	}
	if len(r.outputs.pubs) != 0 {
		t.Errorf("a file outside outputs/ was published: %+v", r.outputs.pubs)
	}
}

func TestUploadPublishesAFileUnderOutputsAsATaskArtifact(t *testing.T) {
	r := newRig(t)
	status, body := r.do(t, http.MethodPut, "/v1/runner/tasks/"+turnTaskID+"/files/outputs/logo.png", runnerKey, strings.NewReader("png"))
	if status != http.StatusNoContent {
		t.Fatalf("upload: %d %s", status, body)
	}
	if len(r.files.puts) != 1 || r.files.puts[0].key != "harness-files/"+wsID+"/"+turnTaskID+"/outputs/logo.png" {
		t.Fatalf("puts: %+v", r.files.puts)
	}
	want := published{wsID, turnTaskID, "outputs/logo.png", "image/png", []byte("png")}
	if len(r.outputs.pubs) != 1 || r.outputs.pubs[0].path != want.path || r.outputs.pubs[0].workspaceID != want.workspaceID ||
		r.outputs.pubs[0].taskID != want.taskID || r.outputs.pubs[0].contentType != want.contentType || string(r.outputs.pubs[0].body) != "png" {
		t.Fatalf("published: %+v", r.outputs.pubs)
	}

	r.outputs.err = errors.New("artifact store down")
	status, body = r.do(t, http.MethodPut, "/v1/runner/tasks/"+turnTaskID+"/files/outputs/clip.mp4", runnerKey, strings.NewReader("mp4"))
	if status < 500 {
		t.Fatalf("a file that could not be published was accepted: %d %s", status, body)
	}
}

func TestTaskRelativeTurnsTheRunnersTaskFolderIntoTaskPaths(t *testing.T) {
	for _, c := range []struct{ in, want string }{
		{"Saved to /data/tasks/" + turnTaskID + "/outputs/agentarea.png.", "Saved to outputs/agentarea.png."},
		{"![logo](/home/me/.agentarea/runner/tasks/" + turnTaskID + "/outputs/a%20b.png)", "![logo](outputs/a%20b.png)"},
		{"[clip](file:///data/tasks/" + turnTaskID + "/outputs/clip.mp4)", "[clip](outputs/clip.mp4)"},
		{"See `/data/tasks/" + turnTaskID + "/notes.md`", "See `notes.md`"},
		{"Another task: /data/tasks/" + otherTask + "/outputs/x.png", "Another task: /data/tasks/" + otherTask + "/outputs/x.png"},
		{"No paths here.", "No paths here."},
	} {
		if got := taskRelative(c.in, turnTaskID); got != c.want {
			t.Errorf("taskRelative(%q) = %q, want %q", c.in, got, c.want)
		}
	}
}

func TestASubtasksOutputsGoToTheTaskItWorksOn(t *testing.T) {
	r := newRig(t)
	status, body := r.do(t, http.MethodPut, "/v1/runner/tasks/"+subTask+"/files/outputs/x.png", runnerKey, strings.NewReader("png"))
	if status != http.StatusNoContent {
		t.Fatalf("upload: %d %s", status, body)
	}
	if len(r.shared.puts) != 1 || r.shared.puts[0] != parentTask+":outputs/x.png=png" || len(r.files.puts) != 0 {
		t.Fatalf("committed %v, own %v", r.shared.puts, r.files.puts)
	}
	if len(r.outputs.pubs) != 1 || r.outputs.pubs[0].taskID != parentTask || r.outputs.pubs[0].path != "outputs/x.png" {
		t.Fatalf("published %+v", r.outputs.pubs)
	}
	status, body = r.do(t, http.MethodPut, "/v1/runner/tasks/"+subTask+"/files/inputs/attachments/IMG.MOV", runnerKey, strings.NewReader("mov"))
	if status != http.StatusNoContent {
		t.Fatalf("upload: %d %s", status, body)
	}
	if len(r.shared.puts) != 1 || len(r.files.puts) != 1 || r.files.puts[0].key != "harness-files/"+wsID+"/"+subTask+"/inputs/attachments/IMG.MOV" {
		t.Fatalf("a file outside outputs/ went to the shared task: shared %v, own %v", r.shared.puts, r.files.puts)
	}
}

func TestAnOutputThatDoesNotReachTheTaskIsNotedAndRetryable(t *testing.T) {
	r := newRig(t)
	r.shared.err = errors.New("workspace_conflict")
	status, body := r.do(t, http.MethodPut, "/v1/runner/tasks/"+subTask+"/files/outputs/deck.pptx", runnerKey, strings.NewReader("pptx"))
	if status != http.StatusServiceUnavailable || !strings.Contains(body, "workspace_conflict") {
		t.Fatalf("lost upload: %d %s", status, body)
	}
	r.shared.err = nil
	r.outputs.err = errors.New("artifact store down")
	if status, _ := r.do(t, http.MethodPut, "/v1/runner/tasks/"+subTask+"/files/outputs/x.png", runnerKey, strings.NewReader("png")); status != http.StatusServiceUnavailable {
		t.Fatalf("unpublished upload: %d", status)
	}
	if status, _ := r.do(t, http.MethodPut, "/v1/runner/tasks/"+turnTaskID+"/files/outputs/y.png", runnerKey, strings.NewReader("png")); status != http.StatusServiceUnavailable {
		t.Fatalf("a task's own unpublished output: %d", status)
	}
	lost := r.tasks.lost[subTask]
	if len(lost) != 2 || !strings.HasPrefix(lost[0], "outputs/deck.pptx (") || !strings.HasPrefix(lost[1], "outputs/x.png (") || len(r.tasks.lost[turnTaskID]) != 1 {
		t.Fatalf("lost = %v", r.tasks.lost)
	}
}

func TestATurnWhoseOutputsDidNotAllArriveFailsNamingThem(t *testing.T) {
	r := newRig(t)
	c := &conn{d: &Deps{Tasks: r.tasks}, log: slog.New(slog.DiscardHandler)}
	done := workflows.RunnerTurnResult{Status: "completed", Response: "Готово"}
	if got := c.withLostOutputs(context.Background(), subTask, done); got != done {
		t.Fatalf("a turn with all its outputs changed: %+v", got)
	}
	r.tasks.lost[subTask] = []string{"outputs/deck.pptx (sandbox expired)"}
	got := c.withLostOutputs(context.Background(), subTask, done)
	if got.Status != "failed" || got.Error != "The CLI finished, but these files it wrote did not reach the task: outputs/deck.pptx (sandbox expired). Its answer was: Готово" {
		t.Fatalf("result = %+v", got)
	}
	if again := c.withLostOutputs(context.Background(), subTask, done); again != done {
		t.Fatalf("a lost output was reported twice: %+v", again)
	}
}

func TestARunnersAgentIsToldWhatOfItsOutputsComesBack(t *testing.T) {
	if fileMaxBytes != 50<<20 || !strings.Contains(outputsLimitNote, "up to 50 MB each") || !strings.Contains(outputsLimitNote, "ffmpeg") {
		t.Fatalf("note = %q", outputsLimitNote)
	}
	if withOutputsLimit("") != outputsLimitNote || withOutputsLimit("Be brief.") != "Be brief.\n\n"+outputsLimitNote {
		t.Fatal("the note does not follow the agent's instructions")
	}
}

func TestRelativePathIsPurePosixPath(t *testing.T) {
	for in, want := range map[string]string{"a//b": "a/b", "./a/./b/": "a/b", "a": "a"} {
		if got, ok := relativePath(in); !ok || got != want {
			t.Errorf("%q: %q %v", in, got, ok)
		}
	}
	for _, in := range []string{"", "/a", "..", "a/../b", ".", "./"} {
		if _, ok := relativePath(in); ok {
			t.Errorf("%q accepted", in)
		}
	}
}

func (r *rig) dial(t *testing.T, ctx context.Context, key string) (*websocket.Conn, *http.Response, error) {
	t.Helper()
	h := http.Header{}
	if key != "" {
		h.Set("Authorization", "Bearer "+key)
	}
	return websocket.Dial(ctx, "ws"+strings.TrimPrefix(r.srv.URL, "http")+"/v1/runner/connect", &websocket.DialOptions{HTTPHeader: h})
}

func sendFrame(t *testing.T, ctx context.Context, c *websocket.Conn, frame map[string]any) {
	t.Helper()
	b, err := json.Marshal(frame)
	if err != nil {
		t.Fatal(err)
	}
	if err := c.Write(ctx, websocket.MessageText, b); err != nil {
		t.Fatal(err)
	}
}

func readFrame(t *testing.T, ctx context.Context, c *websocket.Conn) map[string]any {
	t.Helper()
	_, b, err := c.Read(ctx)
	if err != nil {
		t.Fatal(err)
	}
	var out map[string]any
	if err := json.Unmarshal(b, &out); err != nil {
		t.Fatal(err)
	}
	return out
}

func TestSocketRefusesAnythingButARunnersKey(t *testing.T) {
	r := newRig(t)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	for _, key := range []string{"", memberKey, otherKey, noRunKey} {
		_, res, err := r.dial(t, ctx, key)
		if err == nil || res == nil || res.StatusCode != http.StatusForbidden {
			t.Errorf("key %q: %v %v", key, res, err)
		}
	}
}

func TestSocketClosesOnABadStart(t *testing.T) {
	r := newRig(t)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	c, _, err := r.dial(t, ctx, runnerKey)
	if err != nil {
		t.Fatal(err)
	}
	sendFrame(t, ctx, c, map[string]any{"type": "ping"})
	if _, _, err := c.Read(ctx); websocket.CloseStatus(err) != websocket.StatusPolicyViolation {
		t.Fatalf("ping first: %v", err)
	}
	c, _, err = r.dial(t, ctx, runnerKey)
	if err != nil {
		t.Fatal(err)
	}
	sendFrame(t, ctx, c, map[string]any{"type": "hello"})
	readFrame(t, ctx, c)
	sendFrame(t, ctx, c, map[string]any{"type": "turn.event", "turn_id": "not-a-uuid", "seq": 1})
	if _, _, err := c.Read(ctx); websocket.CloseStatus(err) != websocket.StatusUnsupportedData {
		t.Fatalf("bad frame: %v", err)
	}
}

type turnRun struct {
	res workflows.RunnerTurnResult
	err error
}

func startTurn(ctx context.Context, turns workflows.RunnerTurns, updates chan workflows.RunnerTurnUpdate) chan turnRun {
	out := make(chan turnRun, 1)
	go func() {
		res, err := turns.RunTurn(ctx, workflows.RunnerTurnCall{
			Request: workflows.RunnerTurnRequest{
				TaskID: turnTaskID, AgentID: agentID, WorkspaceID: wsID, Iteration: 1, TurnKey: "1.1", Message: "do it",
			},
			WorkflowID: "task-" + turnTaskID,
			Heartbeat:  func() {},
			Signal: func(_ context.Context, u workflows.RunnerTurnUpdate) error {
				updates <- u
				return nil
			},
		})
		out <- turnRun{res, err}
	}()
	return out
}

func helloed(t *testing.T, ctx context.Context, r *rig) (*websocket.Conn, workflows.RunnerTurns) {
	t.Helper()
	c, _, err := r.dial(t, ctx, runnerKey)
	if err != nil {
		t.Fatal(err)
	}
	sendFrame(t, ctx, c, map[string]any{
		"type": "hello", "capacity": 2, "version": "runner/2", "default_model": "gpt-5.5",
		"models": []any{map[string]any{"name": "gpt-5.5", "reasoning_levels": []string{"low", "high"}}},
	})
	welcome := readFrame(t, ctx, c)
	if welcome["type"] != "welcome" || welcome["client_id"] != clientID || welcome["workspace"] != wsSlug ||
		welcome["kind"] != "codex" || welcome["ping_seconds"] != 10.0 || welcome["lease_seconds"] != 30.0 {
		t.Fatalf("welcome: %v", welcome)
	}
	select {
	case turns := <-r.turns:
		return c, turns
	case <-ctx.Done():
		t.Fatal("no worker registered")
	}
	return nil, nil
}

func TestSocketRoundTripOfATurn(t *testing.T) {
	r := newRig(t)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	c, turns := helloed(t, ctx, r)
	r.workers.mu.Lock()
	w := r.workers.opened[0]
	r.workers.mu.Unlock()
	if w.queue != "runner-turns-"+clientID || w.limits.MaxActivities != 2 {
		t.Fatalf("worker: %+v", w)
	}
	r.clients.mu.Lock()
	if len(r.clients.models) != 1 || r.clients.models[0].Name != "gpt-5.5" || r.clients.dflt != "gpt-5.5" {
		t.Fatalf("hello not recorded: %+v %q", r.clients.models, r.clients.dflt)
	}
	r.clients.mu.Unlock()

	updates := make(chan workflows.RunnerTurnUpdate, 32)
	done := startTurn(ctx, turns, updates)
	assign := readFrame(t, ctx, c)
	turnID, _ := assign["turn_id"].(string)
	want := map[string]any{
		"type": "turn.assign", "task_id": turnTaskID, "agent_id": agentID, "iteration": 1.0, "message": "do it",
		"session_id": nil, "requested_by": "u1", "model": "gpt-5", "reasoning_effort": "high",
		"instructions": "Be brief.\n\n## Skill: s\n\nbody\n\n" + outputsLimitNote, "sandbox": true, "token": "turn-token",
		"mcp_path": "/mcp/clients/" + clientID,
	}
	for k, v := range want {
		if assign[k] != v {
			t.Errorf("assign %s = %v, want %v", k, assign[k], v)
		}
	}
	if d, _ := assign["allow_domains"].([]any); len(d) != 2 || d[0] != "example.com" || d[1] != "storage.example.com" {
		t.Errorf("allow_domains = %v, want the client's hosts and the file store's", assign["allow_domains"])
	}
	if a, _ := assign["actor"].(map[string]any); a["type"] != "user" || a["id"] != "u1" {
		t.Errorf("actor: %v", assign["actor"])
	}
	claims := <-r.tokens.claims
	if claims.TurnID != turnID || claims.ClientID != clientID || claims.ActorType != authn.SubjectUser || claims.OnBehalfOf != "creator" {
		t.Errorf("claims: %+v", claims)
	}
	if alive, _ := r.live.Alive(ctx, turnID); !alive {
		t.Error("turn is not live")
	}

	sendFrame(t, ctx, c, map[string]any{"type": "turn.started", "turn_id": turnID, "session_id": "sess-1"})
	sendFrame(t, ctx, c, map[string]any{"type": "turn.event", "turn_id": turnID, "seq": 1,
		"event": map[string]any{"kind": "message.delta", "item_id": "m1", "text": "Hel"}})
	sendFrame(t, ctx, c, map[string]any{"type": "turn.event", "turn_id": turnID, "seq": 2,
		"event": map[string]any{"kind": "tool.call", "id": "c1", "name": "shell", "arguments": map[string]any{"cmd": "ls"}}})
	sendFrame(t, ctx, c, map[string]any{"type": "turn.event", "turn_id": turnID, "seq": 3,
		"event": map[string]any{"kind": "tool.result", "id": "c1", "name": "shell", "output": strings.Repeat("x", toolOutputMax+5), "exit_code": 0}})
	sendFrame(t, ctx, c, map[string]any{"type": "approval.request", "turn_id": turnID, "request_id": "r1",
		"kind": "command", "tool_name": "shell", "arguments": map[string]any{"cmd": "rm"}})

	note := <-r.broker.notes
	if note.channel != events.TaskLiveChannel(turnTaskID) {
		t.Errorf("live channel: %s", note.channel)
	}
	r.broker.deliveries <- map[string]string{"task_id": turnTaskID, "turn_key": "1.1", "kind": "steer", "message_id": "q1", "text": "also this"}
	steer := readFrame(t, ctx, c)
	if steer["type"] != "turn.steer" || steer["turn_id"] != turnID || steer["message_id"] != "q1" || steer["text"] != "also this" {
		t.Errorf("steer: %v", steer)
	}
	r.broker.deliveries <- map[string]string{"task_id": turnTaskID, "turn_key": "1.1", "kind": "decision", "request_id": "r1", "approved": "true"}
	decision := readFrame(t, ctx, c)
	if decision["type"] != "approval.decision" || decision["approved"] != true || decision["request_id"] != "r1" {
		t.Errorf("decision: %v", decision)
	}
	sendFrame(t, ctx, c, map[string]any{"type": "steer.accepted", "turn_id": turnID, "message_id": "q1"})
	sendFrame(t, ctx, c, map[string]any{"type": "turn.event", "turn_id": turnID, "seq": 4,
		"event": map[string]any{"kind": "message", "item_id": "m1", "text": "Hello: /data/tasks/" + turnTaskID + "/outputs/a.png", "model": "gpt-5"}})
	sendFrame(t, ctx, c, map[string]any{"type": "turn.finished", "turn_id": turnID, "status": "completed", "response": "Hello: /data/tasks/" + turnTaskID + "/outputs/a.png"})

	got := <-done
	if got.err != nil || got.res.Status != "completed" || got.res.Response != "Hello: outputs/a.png" {
		t.Fatalf("turn: %+v", got)
	}
	close(updates)
	var evs []workflows.RunnerTurnEvent
	var asks []workflows.RunnerApprovalAsk
	var steers []workflows.RunnerSteerOutcome
	for u := range updates {
		if u.TurnKey != "1.1" || u.Actor == nil || u.Actor.ID != "u1" {
			t.Errorf("update: %+v", u)
		}
		evs, asks, steers = append(evs, u.Events...), append(asks, u.Approvals...), append(steers, u.Steers...)
	}
	if len(evs) != 3 || evs[0].Kind != "tool.call" || evs[1].Kind != "tool.result" || evs[2].Kind != "message" {
		t.Fatalf("events: %+v", evs)
	}
	if evs[2].Text != "Hello: outputs/a.png" {
		t.Errorf("message: %q", evs[2].Text)
	}
	if !strings.HasSuffix(evs[1].Output, clippedNote) || evs[1].ExitCode == nil || *evs[1].Success != true {
		t.Errorf("tool result: %+v", evs[1])
	}
	if len(asks) != 1 || asks[0].RequestID != "r1" || asks[0].Arguments["cmd"] != "rm" {
		t.Errorf("approvals: %+v", asks)
	}
	if len(steers) != 1 || !steers[0].Accepted {
		t.Errorf("steers: %+v", steers)
	}
	r.tasks.mu.Lock()
	if r.tasks.sessions[turnTaskID] != "sess-1" {
		t.Errorf("session: %v", r.tasks.sessions)
	}
	r.tasks.mu.Unlock()
	if alive, _ := r.live.Alive(ctx, turnID); alive {
		t.Error("turn still live after it finished")
	}
}

func TestALostSocketFailsTheTurnAsLost(t *testing.T) {
	r := newRig(t)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	c, turns := helloed(t, ctx, r)
	done := startTurn(ctx, turns, make(chan workflows.RunnerTurnUpdate, 8))
	readFrame(t, ctx, c)
	_ = c.CloseNow()
	got := <-done
	var appErr *durable.ApplicationError
	if !errors.As(got.err, &appErr) || appErr.Type != workflows.RunnerLostType || appErr.NonRetryable {
		t.Fatalf("lost turn: %+v", got)
	}
}

func TestAStoppedRunCancelsTheCLIsTurn(t *testing.T) {
	r := newRig(t)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	c, turns := helloed(t, ctx, r)
	turnCtx, stop := context.WithCancel(ctx)
	updates := make(chan workflows.RunnerTurnUpdate, 8)
	done := startTurn(turnCtx, turns, updates)
	turnID := readFrame(t, ctx, c)["turn_id"]
	stop()
	if f := readFrame(t, ctx, c); f["type"] != "turn.cancel" || f["turn_id"] != turnID {
		t.Fatalf("cancel: %v", f)
	}
	sendFrame(t, ctx, c, map[string]any{"type": "turn.finished", "turn_id": turnID, "status": "interrupted"})
	if got := <-done; !errors.Is(got.err, context.Canceled) {
		t.Fatalf("stopped turn: %+v", got)
	}
	if u := <-updates; u.TurnKey != "1.1" {
		t.Errorf("the stop's report: %+v", u)
	}
}

func TestATaskOfAnotherClientIsRefused(t *testing.T) {
	r := newRig(t)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	_, turns := helloed(t, ctx, r)
	_, err := turns.RunTurn(ctx, workflows.RunnerTurnCall{Request: workflows.RunnerTurnRequest{TaskID: otherTask, TurnKey: "1.1"}})
	var appErr *durable.ApplicationError
	if !errors.As(err, &appErr) || appErr.Type != "WrongClient" || !appErr.NonRetryable {
		t.Fatalf("wrong client: %v", err)
	}
	_, err = turns.RunTurn(ctx, workflows.RunnerTurnCall{Request: workflows.RunnerTurnRequest{TaskID: uuid.NewString(), TurnKey: "1.1"}})
	if !errors.As(err, &appErr) || appErr.Type != "TaskNotFound" {
		t.Fatalf("missing task: %v", err)
	}
}

func TestParseUpFrame(t *testing.T) {
	turn := uuid.NewString()
	ok := []string{
		`{"type":"hello"}`,
		`{"type":"hello","capacity":16,"models":null,"turns":["` + turn + `"]}`,
		`{"type":"ping","extra":1}`,
		`{"type":"turn.finished","turn_id":"` + turn + `","status":"failed","response":null,"error":"x","session_id":null}`,
		`{"type":"turn.event","turn_id":"` + turn + `","seq":1,"event":{"kind":"tool.result","id":"a","name":"b"}}`,
	}
	for _, s := range ok {
		if _, err := parseUpFrame([]byte(s)); err != nil {
			t.Errorf("%s: %v", s, err)
		}
	}
	bad := []string{
		`{"type":"hello","capacity":17}`,
		`{"type":"nope"}`,
		`{"type":"turn.finished","turn_id":"` + turn + `","status":"done"}`,
		`{"type":"turn.event","turn_id":"` + turn + `","seq":0,"event":{"kind":"message","item_id":"a","text":"b"}}`,
		`{"type":"turn.event","turn_id":"` + turn + `","seq":1,"event":{"kind":"tool.call","id":"a","name":"b","arguments":[]}}`,
		`{"type":"approval.request","turn_id":"` + turn + `","request_id":"r","kind":"other","tool_name":"t"}`,
		`{"type":"turn.started","turn_id":"` + turn + `"}`,
		`[]`,
	}
	for _, s := range bad {
		var pe *protocolError
		if _, err := parseUpFrame([]byte(s)); !errors.As(err, &pe) {
			t.Errorf("%s accepted: %v", s, err)
		}
	}
	if _, err := parseUpFrame([]byte(`"` + strings.Repeat("é", frameMaxChars) + `"`)); err == nil {
		t.Error("an oversized frame was accepted")
	}
}

func TestSignalBatchCarriesAtLeastOneEvent(t *testing.T) {
	big := workflows.RunnerTurnEvent{Kind: "message", Text: strings.Repeat("x", signalMaxChars)}
	if got := signalBatch([]workflows.RunnerTurnEvent{big, big}); len(got) != 1 {
		t.Fatalf("batch: %d", len(got))
	}
	small := workflows.RunnerTurnEvent{Kind: "message", Text: "x"}
	if got := signalBatch([]workflows.RunnerTurnEvent{small, small, small}); len(got) != 3 {
		t.Fatalf("batch: %d", len(got))
	}
}

func TestLiveSnapshotsThrottlePerItem(t *testing.T) {
	now := time.Unix(0, 0)
	l := newLiveSnapshots(func() time.Time { return now })
	if text, _, due := l.addText("a", "He", "text"); !due || text != "He" {
		t.Fatal("first delta not due")
	}
	if _, _, due := l.addText("a", "l", "text"); due {
		t.Fatal("second delta due within the interval")
	}
	now = now.Add(snapshotInterval)
	if text, thinking, due := l.addText("a", "?", "thinking"); !due || text != "Hel" || thinking != "?" {
		t.Fatalf("snapshot: %q %q %v", text, thinking, due)
	}
	if out, due := l.addOutput("c", strings.Repeat("y", progressTailChar+3)); !due || len(out) != progressTailChar {
		t.Fatalf("output tail: %d", len(out))
	}
}
