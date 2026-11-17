package service

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
)

type fakeA2ARuns struct {
	tasks     map[string]agentsapi.A2ATask
	denied    bool
	cancelled []string
	params    map[string]wirejson.Object
	events    []wirejson.Object
	fromNow   bool
}

func (f *fakeA2ARuns) Start(context.Context, agentsapi.A2AStart) (string, error) {
	return "", errors.New("not used")
}

func (f *fakeA2ARuns) Task(_ context.Context, id string, live bool) (agentsapi.A2ATask, bool, error) {
	t, ok := f.tasks[id]
	if ok && live && t.Status == "running" && len(f.cancelled) > 0 {
		t.Status = "cancelled"
	}
	return t, ok, nil
}

func (f *fakeA2ARuns) MayAct(context.Context, agentsapi.A2ATask) error {
	if f.denied {
		return httpx.HTTPError(http.StatusForbidden, "Only a workspace admin may perform this action")
	}
	return nil
}

func (f *fakeA2ARuns) Cancel(_ context.Context, id string) (bool, error) {
	f.cancelled = append(f.cancelled, id)
	return true, nil
}

func (f *fakeA2ARuns) AgentTasks(_ context.Context, _ string, limit, offset int) ([]agentsapi.A2ATask, int64, error) {
	var all []agentsapi.A2ATask
	for i := 0; i < 5; i++ {
		all = append(all, agentsapi.A2ATask{ID: uuid.NewString(), Status: "completed"})
	}
	end := min(offset+limit, len(all))
	return all[offset:end], int64(len(all)), nil
}

func (f *fakeA2ARuns) SetParameters(_ context.Context, id string, p wirejson.Object) error {
	if f.params == nil {
		f.params = map[string]wirejson.Object{}
	}
	f.params[id] = p
	t := f.tasks[id]
	t.Parameters = p
	f.tasks[id] = t
	return nil
}

func (f *fakeA2ARuns) Follow(_ context.Context, _ agentsapi.A2ATask, fromNow bool, emit func(string, wirejson.Object) error) error {
	f.fromNow = fromNow
	for _, e := range f.events {
		typ, _ := e.Get("type")
		data, _ := e.Get("data")
		if err := emit(typ.(string), data.(wirejson.Object)); err != nil {
			return err
		}
	}
	return nil
}

type fakePushSecrets struct{ set, deleted []string }

func (f *fakePushSecrets) Set(_ context.Context, _ authn.Caller, name, _ string) error {
	f.set = append(f.set, name)
	return nil
}

func (f *fakePushSecrets) Delete(_ context.Context, _ authn.Caller, name string) error {
	f.deleted = append(f.deleted, name)
	return nil
}

type a2aWorld struct {
	runs    *fakeA2ARuns
	secrets *fakePushSecrets
	tasks   *a2aTasks
	agent   uuid.UUID
	task    string
}

func newA2AWorld(t *testing.T, status string) a2aWorld {
	t.Helper()
	w := a2aWorld{runs: &fakeA2ARuns{tasks: map[string]agentsapi.A2ATask{}}, secrets: &fakePushSecrets{}, agent: uuid.New(), task: uuid.NewString()}
	w.runs.tasks[w.task] = agentsapi.A2ATask{ID: w.task, AgentID: w.agent.String(), Status: status, UpdatedAt: time.Unix(1700000000, 0).UTC(),
		Result: wirejson.Object{{Key: "response", Value: "done"}}}
	a := NewA2A(&Service{}, A2APorts{Runs: w.runs, PushSecrets: w.secrets,
		PushURL: func(_ context.Context, raw string) error {
			if strings.Contains(raw, "internal") {
				return errors.New("blocked address")
			}
			return nil
		}})
	w.tasks = a.tasks.(*a2aTasks)
	return w
}

func (w a2aWorld) call(method string, params domain.A2AJSON) A2ACall {
	ws, _ := scope.NewWorkspace("w1", "")
	return A2ACall{Method: method, Params: params, AgentID: w.agent, Caller: authn.Caller{Principal: authn.Principal{UserID: "u"}, Workspace: ws},
		Auth: domain.A2AAuth{Authenticated: true, UserID: "u", WorkspaceID: "w1"}}
}

func rpcCode(t *testing.T, err error) int {
	t.Helper()
	var rpc *domain.A2ARPCError
	if !errors.As(err, &rpc) {
		t.Fatalf("not a JSON-RPC error: %v", err)
	}
	return rpc.Code
}

func TestA2AGetTask(t *testing.T) {
	w := newA2AWorld(t, "completed")
	ctx := context.Background()
	got, err := w.tasks.Handle(ctx, w.call("GetTask", domain.A2AJSON{{Key: "id", Value: w.task}}))
	if err != nil {
		t.Fatal(err)
	}
	if id, _ := got.Get("id"); id != w.task {
		t.Errorf("%v", got)
	}
	if arts, _ := got.Get("artifacts"); arts == nil {
		t.Errorf("a completed task carries its answer: %v", got)
	}
	_, err = w.tasks.Handle(ctx, w.call("GetTask", domain.A2AJSON{{Key: "id", Value: uuid.NewString()}}))
	if rpcCode(t, err) != domain.A2ACodeTaskNotFound {
		t.Errorf("%v", err)
	}
	_, err = w.tasks.Handle(ctx, w.call("GetTask", domain.A2AJSON{{Key: "id", Value: "nope"}}))
	if rpcCode(t, err) != domain.A2ACodeInvalidParams {
		t.Errorf("%v", err)
	}
	_, err = w.tasks.Handle(ctx, w.call("GetTask", domain.A2AJSON{}))
	if rpcCode(t, err) != domain.A2ACodeInvalidParams {
		t.Errorf("%v", err)
	}
}

func TestA2ATaskOfAnotherAgentIsNotFound(t *testing.T) {
	w := newA2AWorld(t, "completed")
	other := w.runs.tasks[w.task]
	other.AgentID = uuid.NewString()
	w.runs.tasks[w.task] = other
	_, err := w.tasks.Handle(context.Background(), w.call("GetTask", domain.A2AJSON{{Key: "id", Value: w.task}}))
	if rpcCode(t, err) != domain.A2ACodeTaskNotFound {
		t.Errorf("%v", err)
	}
}

func TestA2AAgentKeySeesOnlyItsOwnTasks(t *testing.T) {
	w := newA2AWorld(t, "completed")
	call := w.call("GetTask", domain.A2AJSON{{Key: "id", Value: w.task}})
	call.Auth.AgentKeyID = "k1"
	if _, err := w.tasks.Handle(context.Background(), call); rpcCode(t, err) != domain.A2ACodeTaskNotFound {
		t.Errorf("a task no key started: %v", err)
	}
	task := w.runs.tasks[w.task]
	task.Metadata = wirejson.Object{{Key: domain.A2AAgentKeyMetadata, Value: "k1"}}
	w.runs.tasks[w.task] = task
	if _, err := w.tasks.Handle(context.Background(), call); err != nil {
		t.Errorf("its own: %v", err)
	}
	list := w.call("ListTasks", nil)
	list.Auth.AgentKeyID = "k1"
	if _, err := w.tasks.Handle(context.Background(), list); rpcCode(t, err) != domain.A2ACodeUnsupportedOperation {
		t.Errorf("%v", err)
	}
}

func TestA2ACancelTask(t *testing.T) {
	ctx := context.Background()
	w := newA2AWorld(t, "running")
	got, err := w.tasks.Handle(ctx, w.call("CancelTask", domain.A2AJSON{{Key: "id", Value: w.task}}))
	if err != nil || len(w.runs.cancelled) != 1 {
		t.Fatalf("%v %v", got, err)
	}
	status, _ := got.Get("status")
	if state, _ := status.(domain.A2AJSON).Get("state"); state != domain.A2AStateCanceled {
		t.Errorf("the cancelled task is read again: %v", got)
	}
	done := newA2AWorld(t, "completed")
	_, err = done.tasks.Handle(ctx, done.call("CancelTask", domain.A2AJSON{{Key: "id", Value: done.task}}))
	if rpcCode(t, err) != domain.A2ACodeTaskNotCancelable || len(done.runs.cancelled) != 0 {
		t.Errorf("%v", err)
	}
	stranger := newA2AWorld(t, "running")
	stranger.runs.denied = true
	_, err = stranger.tasks.Handle(ctx, stranger.call("CancelTask", domain.A2AJSON{{Key: "id", Value: stranger.task}}))
	var he *httpx.Error
	if !errors.As(err, &he) || he.Status != http.StatusForbidden {
		t.Errorf("a run another member started answers 403: %v", err)
	}
}

func TestA2AListTasksPages(t *testing.T) {
	w := newA2AWorld(t, "completed")
	ctx := context.Background()
	got, err := w.tasks.Handle(ctx, w.call("ListTasks", domain.A2AJSON{{Key: "pageSize", Value: float64(2)}}))
	if err != nil {
		t.Fatal(err)
	}
	next, _ := got.Get("nextPageToken")
	total, _ := got.Get("totalSize")
	tasks, _ := got.Get("tasks")
	if len(tasks.([]any)) != 2 || next != domain.A2AEncodePageToken(2) || total != 5 {
		t.Errorf("%v", got)
	}
	last, err := w.tasks.Handle(ctx, w.call("ListTasks", domain.A2AJSON{{Key: "pageSize", Value: float64(2)}, {Key: "pageToken", Value: domain.A2AEncodePageToken(4)}}))
	if err != nil {
		t.Fatal(err)
	}
	if next, _ := last.Get("nextPageToken"); next != "" {
		t.Errorf("the last page has no next token: %v", last)
	}
	if _, err := w.tasks.Handle(ctx, w.call("ListTasks", domain.A2AJSON{{Key: "contextId", Value: "c"}})); rpcCode(t, err) != domain.A2ACodeUnsupportedOperation {
		t.Errorf("%v", err)
	}
}

func TestA2APushConfigLifecycle(t *testing.T) {
	ctx := context.Background()
	w := newA2AWorld(t, "running")
	created, err := w.tasks.Handle(ctx, w.call("CreateTaskPushNotificationConfig", domain.A2AJSON{
		{Key: "taskId", Value: w.task}, {Key: "id", Value: "c1"}, {Key: "url", Value: "https://hooks.example/a"}, {Key: "token", Value: "s3cret"}}))
	if err != nil {
		t.Fatal(err)
	}
	if tok, has := created.Get("token"); has {
		t.Errorf("the token is never returned: %v", tok)
	}
	if len(w.secrets.set) != 1 || w.secrets.set[0] != "a2a_push_token:"+w.task+":c1" {
		t.Errorf("token secret: %v", w.secrets.set)
	}
	if _, ok := w.runs.params[w.task]; !ok {
		t.Fatal("the url is stored in the task parameters")
	}
	got, err := w.tasks.Handle(ctx, w.call("GetTaskPushNotificationConfig", domain.A2AJSON{{Key: "taskId", Value: w.task}, {Key: "id", Value: "c1"}}))
	if url, _ := got.Get("url"); err != nil || url != "https://hooks.example/a" {
		t.Errorf("%v %v", got, err)
	}
	list, err := w.tasks.Handle(ctx, w.call("ListTaskPushNotificationConfigs", domain.A2AJSON{{Key: "taskId", Value: w.task}}))
	if configs, _ := list.Get("configs"); err != nil || len(configs.([]any)) != 1 {
		t.Errorf("%v %v", list, err)
	}
	if _, err := w.tasks.Handle(ctx, w.call("GetTaskPushNotificationConfig", domain.A2AJSON{{Key: "taskId", Value: w.task}, {Key: "id", Value: "zz"}})); rpcCode(t, err) != domain.A2ACodeTaskNotFound {
		t.Errorf("%v", err)
	}
	if res, err := w.tasks.Handle(ctx, w.call("DeleteTaskPushNotificationConfig", domain.A2AJSON{{Key: "taskId", Value: w.task}, {Key: "id", Value: "c1"}})); err != nil || res != nil {
		t.Errorf("a delete answers null: %v %v", res, err)
	}
	if len(w.secrets.deleted) != 1 {
		t.Errorf("the token secret goes with the config: %v", w.secrets.deleted)
	}
	list, _ = w.tasks.Handle(ctx, w.call("ListTaskPushNotificationConfigs", domain.A2AJSON{{Key: "taskId", Value: w.task}}))
	if len(list) != 0 {
		t.Errorf("%v", list)
	}
}

func TestA2APushConfigRefusals(t *testing.T) {
	ctx := context.Background()
	w := newA2AWorld(t, "running")
	create := func(extra ...domain.A2AMember) error {
		p := domain.A2AJSON{{Key: "taskId", Value: w.task}, {Key: "url", Value: "https://hooks.example/a"}}
		_, err := w.tasks.Handle(ctx, w.call("CreateTaskPushNotificationConfig", append(p, extra...)))
		return err
	}
	if err := create(domain.A2AMember{Key: "authentication", Value: domain.A2AJSON{{Key: "scheme", Value: "Bearer"}}}); rpcCode(t, err) != domain.A2ACodeInvalidParams {
		t.Errorf("authentication schemes: %v", err)
	}
	_, err := w.tasks.Handle(ctx, w.call("CreateTaskPushNotificationConfig", domain.A2AJSON{{Key: "taskId", Value: w.task}, {Key: "url", Value: "http://internal.local/x"}}))
	if rpcCode(t, err) != domain.A2ACodeInvalidParams || !strings.Contains(err.Error(), "Unsafe webhook url") {
		t.Errorf("unsafe url: %v", err)
	}
	_, err = w.tasks.Handle(ctx, w.call("CreateTaskPushNotificationConfig", domain.A2AJSON{{Key: "url", Value: "https://hooks.example/a"}}))
	if rpcCode(t, err) != domain.A2ACodeInvalidParams {
		t.Errorf("task id: %v", err)
	}
	if err := create(); err != nil {
		t.Errorf("a plain config: %v", err)
	}
}

func TestA2AStreamSubscribe(t *testing.T) {
	ctx := context.Background()
	w := newA2AWorld(t, "running")
	w.runs.events = []wirejson.Object{
		{{Key: "type", Value: "task.tool.call"}, {Key: "data", Value: wirejson.Object{{Key: "tool_name", Value: "search"}}}},
		{{Key: "type", Value: "llm.call.chunk"}, {Key: "data", Value: wirejson.Object{{Key: "chunk", Value: "par"}}}},
		{{Key: "type", Value: "task.completed"}, {Key: "data", Value: wirejson.Object{{Key: "result", Value: "partial answer"}}}},
		{{Key: "type", Value: "task.tool.call"}, {Key: "data", Value: wirejson.Object{}}},
	}
	var got []domain.A2AJSON
	err := w.tasks.Stream(ctx, w.call("SubscribeToTask", domain.A2AJSON{{Key: "id", Value: w.task}}), func(ev domain.A2AJSON) error {
		got = append(got, ev)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	var kinds []string
	for _, ev := range got {
		kinds = append(kinds, ev[0].Key)
	}
	want := []string{"task", "statusUpdate", "artifactUpdate", "artifactUpdate", "statusUpdate"}
	if strings.Join(kinds, ",") != strings.Join(want, ",") {
		t.Errorf("a terminal event ends the stream: %v", kinds)
	}
	if !w.runs.fromNow {
		t.Error("a subscription follows what happens next")
	}
	done := newA2AWorld(t, "completed")
	err = done.tasks.Stream(ctx, done.call("SubscribeToTask", domain.A2AJSON{{Key: "id", Value: done.task}}), func(domain.A2AJSON) error { return nil })
	if rpcCode(t, err) != domain.A2ACodeUnsupportedOperation || !strings.Contains(err.Error(), "TASK_STATE_COMPLETED") {
		t.Errorf("a finished task cannot be subscribed to: %v", err)
	}
}

func TestA2ADispatchStreamErrorBeforeFirstEventIsPlain(t *testing.T) {
	w := newA2AWorld(t, "completed")
	a := NewA2A(&Service{}, A2APorts{Runs: w.runs})
	adm := A2AAdmission{
		Agent: domain.Agent{ID: w.agent.String(), WorkspaceID: "w1"}, Principal: &authn.Principal{UserID: "u", AccessibleWorkspaces: []string{"w1"}},
		Auth: domain.A2AAuth{Authenticated: true, UserID: "u", WorkspaceID: "w1"},
	}
	req := domain.A2ARPCRequest{ID: "1", Method: "SubscribeToTask", HasParams: true, Params: domain.A2AJSON{{Key: "id", Value: w.task}}}
	emitted := 0
	body, err := a.DispatchStream(context.Background(), adm, "rpc", req, "1.0", func(domain.A2AJSON, bool) error { emitted++; return nil })
	if err != nil || emitted != 0 || body == nil {
		t.Fatalf("%v %v %d", body, err, emitted)
	}
	if e, _ := body.Get("error"); e == nil {
		t.Errorf("%v", body)
	}
}
