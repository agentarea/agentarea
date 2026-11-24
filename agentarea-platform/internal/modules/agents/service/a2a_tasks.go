package service

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
)

// a2aTasks is AgentAreaRequestHandler: the A2A calls of one agent over runs.
type a2aTasks struct{ a *A2A }

var _ A2ATasks = (*a2aTasks)(nil)

var errA2AStop = errors.New("a2a stream ends")

func (t *a2aTasks) runs() agentsapi.A2ARuns { return t.a.d.Runs }

func (t *a2aTasks) ctx(ctx context.Context, call A2ACall) context.Context {
	return authn.WithCaller(ctx, call.Caller)
}

// httpFailure is the HTTP answer of a refused permission, which the
// dispatcher re-raises instead of folding into a JSON-RPC error.
func httpFailure(err error) error {
	switch {
	case errors.Is(err, authz.ErrDenied):
		return httpx.HTTPError(http.StatusForbidden, "Permission denied").Wrap(err)
	case errors.Is(err, authz.ErrNotWorkspaceAdmin):
		return httpx.HTTPError(http.StatusForbidden, "Only a workspace admin may perform this action").Wrap(err)
	}
	return err
}

// requireAvailable is _require_available_agent.
func (a *A2A) requireAvailable(ctx context.Context, ws scope.Workspace, id uuid.UUID) (domain.Agent, error) {
	var agent domain.Agent
	var found bool
	err := a.s.read(ctx, ws, func(sess db.Session) error {
		var err error
		agent, found, err = a.s.store.Get(ctx, sess, id)
		return err
	})
	if err != nil {
		return agent, err
	}
	if !found {
		return agent, domain.A2AInvalidParams(fmt.Sprintf("Agent with ID %s does not exist", id))
	}
	if agent.Status != "" && !a2aAvailable(agent.Status) {
		return agent, domain.A2AInvalidParams(fmt.Sprintf("Agent %s (ID: %s) is not available (status: %s)", agent.Name, id, agent.Status))
	}
	return agent, nil
}

// ownedTask is _owned_task: the task, which must be this agent's, and the
// agent key's own when a key made the call.
func (t *a2aTasks) ownedTask(ctx context.Context, call A2ACall, raw string, live bool) (agentsapi.A2ATask, error) {
	id, err := uuid.Parse(raw)
	if err != nil {
		return agentsapi.A2ATask{}, domain.A2AInvalidParams("Invalid task ID: " + raw)
	}
	task, ok, err := t.runs().Task(ctx, id.String(), live)
	if err != nil {
		return task, err
	}
	missing := domain.A2ATaskNotFound("Task not found: " + raw)
	if !ok || task.AgentID != call.AgentID.String() {
		return task, missing
	}
	if key := call.Auth.AgentKeyID; key != "" {
		if v, _ := A2AFromWire(task.Metadata).(domain.A2AJSON).Get(domain.A2AAgentKeyMetadata); v != key {
			return task, missing
		}
	}
	return task, nil
}

// taskToActOn is _task_to_act_on: an owned task the caller started or administers the workspace of.
func (t *a2aTasks) taskToActOn(ctx context.Context, call A2ACall, raw string, live bool) (agentsapi.A2ATask, error) {
	task, err := t.ownedTask(ctx, call, raw, live)
	if err != nil {
		return task, err
	}
	if err := t.runs().MayAct(ctx, task); err != nil {
		return task, httpFailure(err)
	}
	return task, nil
}

func a2aRow(t agentsapi.A2ATask) domain.A2ATaskRow {
	row := domain.A2ATaskRow{ID: t.ID, Status: t.Status, ErrorMessage: t.Error}
	if t.Result != nil {
		row.Result = A2AFromWire(t.Result)
	}
	row.Metadata, _ = A2AFromWire(t.Metadata).(domain.A2AJSON)
	if !t.UpdatedAt.IsZero() {
		at := t.UpdatedAt
		row.UpdatedAt = &at
	}
	return row
}

func (t *a2aTasks) taskJSON(task agentsapi.A2ATask) domain.A2AJSON {
	return domain.A2ATask(a2aRow(task), t.a.now())
}

func (a *A2A) now() time.Time { return time.Now().UTC() }

func (t *a2aTasks) params(task agentsapi.A2ATask) domain.A2AJSON {
	p, _ := A2AFromWire(task.Parameters).(domain.A2AJSON)
	return p
}

// registerPush is _register_push_config: the url in the task's parameters, the token in the secret store.
func (t *a2aTasks) registerPush(ctx context.Context, call A2ACall, task agentsapi.A2ATask, cfg domain.A2APushConfig) (domain.A2AJSON, error) {
	if cfg.URL == "" {
		return nil, domain.A2AInvalidParams("Push notification config url is required")
	}
	if cfg.Authentication {
		return nil, domain.A2AInvalidParams("Push notification authentication schemes are not supported; send a token instead")
	}
	if t.a.d.PushURL == nil || t.a.d.PushSecrets == nil {
		return nil, &UnwiredError{Feature: "A2A push notifications"}
	}
	if err := t.a.d.PushURL(ctx, cfg.URL); err != nil {
		return nil, domain.A2AInvalidParams("Unsafe webhook url: " + err.Error())
	}
	id := cfg.ID
	if id == "" {
		id = strings.ReplaceAll(uuid.NewString(), "-", "")
	}
	next, stored := domain.A2AUpsertPushConfig(t.params(task), cfg.URL, id)
	if cfg.Token != "" {
		if err := t.a.d.PushSecrets.Set(ctx, call.Caller, domain.A2APushTokenSecret(task.ID, id), cfg.Token); err != nil {
			return nil, err
		}
	}
	if err := t.runs().SetParameters(ctx, task.ID, A2AToWire(next).(wirejson.Object)); err != nil {
		return nil, err
	}
	return stored, nil
}

// submit is _submit up to the task it started.
func (t *a2aTasks) submit(ctx context.Context, call A2ACall) (agentsapi.A2ATask, error) {
	req, perr := domain.A2ASendParams(call.Params)
	if perr != nil {
		return agentsapi.A2ATask{}, perr
	}
	_, err := t.a.requireAvailable(ctx, call.Caller.Workspace, call.AgentID)
	if err != nil {
		return agentsapi.A2ATask{}, err
	}
	text := domain.A2AMessageText(req.Parts)
	if strings.TrimSpace(text) == "" {
		return agentsapi.A2ATask{}, domain.A2AInvalidParams("Message must contain non-empty text content")
	}
	if req.TaskID != "" {
		return agentsapi.A2ATask{}, domain.A2AUnsupportedOperation("Sending a message to an existing task is not supported; start a new task")
	}
	nt := domain.A2ABuildTask(domain.A2AMessageIn{
		Parts: req.Parts, ContextID: req.ContextID, ClientMetadata: req.Metadata, AgentID: call.AgentID.String(), Auth: call.Auth,
		UserID: call.Caller.UserID, WorkspaceID: call.Caller.Workspace.ID(), Method: call.Method, RequestID: call.RequestID, Now: t.a.now(),
	})
	source := "user:" + call.Caller.UserID
	if c := call.Caller.Credential; c != nil && c.Kind == authn.KindAPIKey && c.KeyID != "" {
		source = "a2a:" + c.KeyID
	}
	approval, _ := nt.Metadata.Get("requires_human_approval")
	id, err := t.runs().Start(ctx, agentsapi.A2AStart{
		AgentID: call.AgentID.String(), Description: nt.Description, Metadata: a2aPlainMap(nt.Metadata), Source: source,
		RequiresHumanApproval: approval == true,
	})
	if err != nil {
		return agentsapi.A2ATask{}, t.startFailure(ctx, call, err)
	}
	task, ok, err := t.runs().Task(ctx, id, false)
	if err != nil {
		return task, err
	}
	if !ok {
		return task, fmt.Errorf("task %s vanished after creation", id)
	}
	if req.Push != nil && req.Push.URL != "" {
		if _, err := t.registerPush(ctx, call, task, *req.Push); err != nil {
			var rpc *domain.A2ARPCError
			if !errors.As(err, &rpc) {
				return task, err
			}
			t.a.warn(ctx, "Ignoring invalid inline push notification config", "task_id", task.ID, "error", err.Error())
		} else if refreshed, ok, err := t.runs().Task(ctx, id, false); err == nil && ok {
			task = refreshed
		}
	}
	return task, nil
}

func (t *a2aTasks) startFailure(ctx context.Context, call A2ACall, err error) error {
	switch {
	case errors.Is(err, agentsapi.ErrA2AModelNotConfigured):
		return domain.A2AInvalidParams("This agent has no model configured; select a model for it before sending a message")
	case errors.Is(err, agentsapi.ErrA2ASpendCap):
		return domain.A2AInvalidRequest("The workspace has reached its monthly spend cap")
	case errors.Is(err, agentsapi.ErrA2ARejected):
		t.a.warn(ctx, "A2A task submission rejected", "agent_id", call.AgentID.String(), "error", err.Error())
		return domain.A2AInvalidParams("Invalid parameters")
	}
	return httpFailure(err)
}

// Handle answers one non-streaming call.
func (t *a2aTasks) Handle(ctx context.Context, call A2ACall) (domain.A2AJSON, error) {
	ctx = t.ctx(ctx, call)
	switch call.Method {
	case "SendMessage":
		task, err := t.submit(ctx, call)
		if err != nil {
			return nil, err
		}
		return domain.A2AJSON{{Key: "task", Value: t.taskJSON(task)}}, nil
	case "GetTask":
		ref, perr := domain.A2AIDParams(call.Params)
		if perr != nil {
			return nil, perr
		}
		task, err := t.ownedTask(ctx, call, ref.TaskID, true)
		if err != nil {
			return nil, err
		}
		return t.taskJSON(task), nil
	case "CancelTask":
		return t.cancel(ctx, call)
	case "ListTasks":
		return t.list(ctx, call)
	case "CreateTaskPushNotificationConfig":
		return t.createPush(ctx, call)
	case "GetTaskPushNotificationConfig":
		return t.getPush(ctx, call)
	case "ListTaskPushNotificationConfigs":
		return t.listPush(ctx, call)
	case "DeleteTaskPushNotificationConfig":
		return t.deletePush(ctx, call)
	}
	return nil, domain.A2AUnsupportedOperation("Method " + call.Method + " is not supported.")
}

func (t *a2aTasks) cancel(ctx context.Context, call A2ACall) (domain.A2AJSON, error) {
	ref, perr := domain.A2AIDParams(call.Params)
	if perr != nil {
		return nil, perr
	}
	task, err := t.taskToActOn(ctx, call, ref.TaskID, true)
	if err != nil {
		return nil, err
	}
	if state, _ := domain.A2ATaskState(task.Status); domain.A2ATerminalState(state) {
		return nil, domain.A2ATaskNotCancelable(fmt.Sprintf("Task cannot be cancelled (current status: %s)", task.Status))
	}
	ok, err := t.runs().Cancel(ctx, task.ID)
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, domain.A2AInternal("Task cancellation failed")
	}
	updated, found, err := t.runs().Task(ctx, task.ID, true)
	if err != nil {
		return nil, err
	}
	if !found {
		updated = task
	}
	return t.taskJSON(updated), nil
}

func (t *a2aTasks) list(ctx context.Context, call A2ACall) (domain.A2AJSON, error) {
	if call.Auth.AgentKeyID != "" {
		return nil, domain.A2AUnsupportedOperation("ListTasks is not available to an agent's key; read the tasks it started with GetTask")
	}
	req, perr := domain.A2AListParams(call.Params)
	if perr != nil {
		return nil, perr
	}
	tasks, total, err := t.runs().AgentTasks(ctx, call.AgentID.String(), req.PageSize, req.Offset)
	if err != nil {
		return nil, err
	}
	out := make([]any, len(tasks))
	for i, task := range tasks {
		j := t.taskJSON(task)
		if !req.IncludeArtifacts {
			j.Delete("artifacts")
		}
		out[i] = j
	}
	next := ""
	if end := req.Offset + len(tasks); int64(end) < total {
		next = domain.A2AEncodePageToken(end)
	}
	return domain.A2AJSON{
		{Key: "tasks", Value: out}, {Key: "nextPageToken", Value: next},
		{Key: "pageSize", Value: req.PageSize}, {Key: "totalSize", Value: int(total)},
	}, nil
}

func (t *a2aTasks) createPush(ctx context.Context, call A2ACall) (domain.A2AJSON, error) {
	cfg, perr := domain.A2APushParams(call.Params)
	if perr != nil {
		return nil, perr
	}
	if cfg.TaskID == "" {
		return nil, domain.A2AInvalidParams("Push notification config taskId is required")
	}
	task, err := t.taskToActOn(ctx, call, cfg.TaskID, false)
	if err != nil {
		return nil, err
	}
	stored, err := t.registerPush(ctx, call, task, cfg)
	if err != nil {
		return nil, err
	}
	return domain.A2APushResult(task.ID, stored), nil
}

func (t *a2aTasks) getPush(ctx context.Context, call A2ACall) (domain.A2AJSON, error) {
	ref, perr := domain.A2AConfigParams(call.Params, true)
	if perr != nil {
		return nil, perr
	}
	task, err := t.taskToActOn(ctx, call, ref.TaskID, false)
	if err != nil {
		return nil, err
	}
	cfg, ok := domain.A2AFindPushConfig(t.params(task), ref.ConfigID)
	if !ok {
		return nil, domain.A2ATaskNotFound("Push notification config not found")
	}
	return domain.A2APushResult(task.ID, cfg), nil
}

func (t *a2aTasks) listPush(ctx context.Context, call A2ACall) (domain.A2AJSON, error) {
	ref, perr := domain.A2AConfigParams(call.Params, false)
	if perr != nil {
		return nil, perr
	}
	task, err := t.taskToActOn(ctx, call, ref.TaskID, false)
	if err != nil {
		return nil, err
	}
	configs := []any{}
	for _, c := range domain.A2AStoredPushConfigs(t.params(task)) {
		configs = append(configs, domain.A2APushResult(task.ID, c))
	}
	if len(configs) == 0 {
		return domain.A2AJSON{}, nil
	}
	return domain.A2AJSON{{Key: "configs", Value: configs}}, nil
}

func (t *a2aTasks) deletePush(ctx context.Context, call A2ACall) (domain.A2AJSON, error) {
	ref, perr := domain.A2AConfigParams(call.Params, true)
	if perr != nil {
		return nil, perr
	}
	task, err := t.taskToActOn(ctx, call, ref.TaskID, false)
	if err != nil {
		return nil, err
	}
	next, removed := domain.A2ADeletePushConfig(t.params(task), ref.ConfigID)
	if !removed {
		return nil, nil
	}
	if err := t.runs().SetParameters(ctx, task.ID, A2AToWire(next).(wirejson.Object)); err != nil {
		return nil, err
	}
	if t.a.d.PushSecrets != nil {
		if err := t.a.d.PushSecrets.Delete(ctx, call.Caller, domain.A2APushTokenSecret(task.ID, ref.ConfigID)); err != nil {
			t.a.warn(ctx, "Could not delete A2A push token secret", "task_id", task.ID, "error", err.Error())
		}
	}
	return nil, nil
}

// Stream answers SendStreamingMessage and SubscribeToTask.
func (t *a2aTasks) Stream(ctx context.Context, call A2ACall, emit func(domain.A2AJSON) error) error {
	ctx = t.ctx(ctx, call)
	switch call.Method {
	case "SendStreamingMessage":
		task, err := t.submit(ctx, call)
		if err != nil {
			return err
		}
		if err := emit(domain.A2AJSON{{Key: "task", Value: t.taskJSON(task)}}); err != nil {
			return err
		}
		return t.follow(ctx, task, false, emit)
	case "SubscribeToTask":
		ref, perr := domain.A2AIDParams(call.Params)
		if perr != nil {
			return perr
		}
		task, err := t.ownedTask(ctx, call, ref.TaskID, true)
		if err != nil {
			return err
		}
		if state, _ := domain.A2ATaskState(task.Status); domain.A2ATerminalState(state) {
			return domain.A2AUnsupportedOperation(fmt.Sprintf("Task %s is in terminal state %s", task.ID, state))
		}
		if err := emit(domain.A2AJSON{{Key: "task", Value: t.taskJSON(task)}}); err != nil {
			return err
		}
		return t.follow(ctx, task, true, emit)
	}
	return domain.A2AUnsupportedOperation("Stream not supported")
}

// follow is _follow: the task's events, mapped, until one ends the stream.
func (t *a2aTasks) follow(ctx context.Context, task agentsapi.A2ATask, fromNow bool, emit func(domain.A2AJSON) error) error {
	contextID := domain.A2AContextID(a2aRow(task))
	stream := domain.A2AStream{TaskID: task.ID, ContextID: contextID, NewID: func() string { return strings.ReplaceAll(uuid.NewString(), "-", "") }}
	err := t.runs().Follow(ctx, task, fromNow, func(eventType string, data wirejson.Object) error {
		d, _ := A2AFromWire(data).(domain.A2AJSON)
		stream.Now = t.a.now()
		events, done := stream.A2AWorkflowEvent(eventType, d)
		for _, ev := range events {
			if err := emit(ev); err != nil {
				return err
			}
		}
		if done {
			return errA2AStop
		}
		return nil
	})
	if errors.Is(err, errA2AStop) {
		return nil
	}
	return err
}

func a2aPlainMap(o domain.A2AJSON) map[string]any {
	m, _ := a2aPlain(o).(map[string]any)
	return m
}

func a2aPlain(v any) any {
	switch x := v.(type) {
	case domain.A2AJSON:
		m := make(map[string]any, len(x))
		for _, kv := range x {
			m[kv.Key] = a2aPlain(kv.Value)
		}
		return m
	case []any:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = a2aPlain(e)
		}
		return out
	}
	return v
}
