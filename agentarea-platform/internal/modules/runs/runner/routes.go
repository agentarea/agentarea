package runner

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"mime"
	"net/http"
	"path"
	"strings"
	"time"

	"github.com/coder/websocket"
	"github.com/go-chi/chi/v5"
	"github.com/redis/go-redis/v9"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	identityapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/workflows"
)

// Gate is the edge's authentication as the runner routes use it.
type Gate interface {
	Authenticate(ctx context.Context, r *http.Request) (authn.Principal, error)
	Caller(ctx context.Context, p authn.Principal, route authn.Route) (authn.Caller, error)
	RunnerKey(ctx context.Context, token string) (*authn.Principal, error)
	EnterAsRunner(p authn.Principal, ws scope.Workspace) (authn.Caller, error)
}

// Workers opens the Temporal worker a socket polls its client's turns with.
type Workers interface {
	NewWorker(queue string, limits durable.Limits) durable.Worker
	Executor() durable.Executor
}

// Presence marks a client's runner connected (runner_presence.py).
type Presence interface {
	Mark(ctx context.Context, clientID string) error
}

// Deps are what the runner routes need; app passes them in.
type Deps struct {
	Tasks    Tasks
	Gate     Gate
	Clients  agentsapi.RunnerClients
	Slugs    identityapi.WorkspaceSlugs
	Broker   events.Broker
	Presence Presence
	// Files is the default bucket, where harness files live.
	Files   blob.Store
	Workers Workers
	Tokens  authn.TurnTokens
	Live    authn.LiveTurns
	Log     *slog.Logger
	Now     func() time.Time

	register registrar
}

// RedisPresence keeps runners:online:<client> for three missed pings.
type RedisPresence struct{ RDB redis.Cmdable }

// Mark sets the client's presence key.
func (p RedisPresence) Mark(ctx context.Context, clientID string) error {
	return p.RDB.Set(ctx, "runners:online:"+clientID, "1", leaseSeconds*time.Second).Err()
}

// Online is runner_presence.online: the clients whose presence key is set.
func (p RedisPresence) Online(ctx context.Context, clientIDs []string) (map[string]bool, error) {
	out := map[string]bool{}
	if len(clientIDs) == 0 {
		return out, nil
	}
	keys := make([]string, len(clientIDs))
	for i, id := range clientIDs {
		keys[i] = "runners:online:" + id
	}
	values, err := p.RDB.MGet(ctx, keys...).Result()
	if err != nil {
		return nil, err
	}
	for i, v := range values {
		if s, ok := v.(string); ok && s != "" {
			out[clientIDs[i]] = true
		}
	}
	return out, nil
}

type handlers struct {
	d    *Deps
	errs *httpx.Errors
}

// Mount registers GET /v1/runner/whoami, PUT /v1/runner/tasks/{task_id}/files/*
// and the socket /v1/runner/connect.
func Mount(r chi.Router, errs *httpx.Errors, d Deps) {
	if d.Log == nil {
		d.Log = slog.Default()
	}
	if d.Now == nil {
		d.Now = time.Now
	}
	if d.register == nil {
		d.register = workflows.RegisterRunnerTurns
	}
	h := &handlers{d: &d, errs: errs}
	r.Get("/v1/runner/whoami", h.whoami)
	r.Put("/v1/runner/tasks/{task_id}/files/*", h.upload)
	r.Get("/v1/runner/connect", h.connect)
}

const (
	detailOnlyRunnerKey = "Only a runner key is accepted"
	detailNoClient      = "Client not found"
	detailNoTask        = "Task not found"
	detailRelative      = "File path must be relative"
	detailTooLarge      = "File too large"
)

// runnerClient is _runner_client: the client the key is bound to, if it is
// still in the key's workspace.
func (h *handlers) runnerClient(ctx context.Context, p authn.Principal) (agentsapi.RunnerClient, bool, error) {
	if p.BoundClientID == "" || p.BoundWorkspaceID == "" {
		return agentsapi.RunnerClient{}, false, nil
	}
	ws, err := scope.NewWorkspace(p.BoundWorkspaceID, "")
	if err != nil {
		return agentsapi.RunnerClient{}, false, nil
	}
	return h.d.Clients.Client(ctx, ws, p.BoundClientID)
}

// admit is bind_runner_client and get_user_context: only a client's runner
// key, acting in that client's workspace.
func (h *handlers) admit(w http.ResponseWriter, r *http.Request) (authn.Principal, authn.Caller, agentsapi.RunnerClient, bool) {
	ctx := r.Context()
	fail := func(err error) (authn.Principal, authn.Caller, agentsapi.RunnerClient, bool) {
		h.errs.Write(w, r, err)
		return authn.Principal{}, authn.Caller{}, agentsapi.RunnerClient{}, false
	}
	p, err := h.d.Gate.Authenticate(ctx, r)
	if err != nil {
		return fail(err)
	}
	if p.BoundClientID == "" {
		return fail(httpx.Forbidden(detailOnlyRunnerKey))
	}
	client, ok, err := h.runnerClient(ctx, p)
	if err != nil {
		return fail(err)
	}
	if !ok {
		return fail(httpx.NotFound(detailNoClient))
	}
	slug, err := h.d.Slugs.Slug(ctx, client.WorkspaceID)
	if err != nil {
		return fail(err)
	}
	c, err := h.d.Gate.Caller(ctx, p, authn.Route{Binding: &authn.Binding{
		WorkspaceID: client.WorkspaceID, WorkspaceSlug: slug, ClientID: p.BoundClientID,
	}})
	if err != nil {
		return fail(err)
	}
	return p, c, client, true
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	b, err := json.Marshal(v)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(b)
}

// whoami is runner_whoami: the client this runner key serves.
func (h *handlers) whoami(w http.ResponseWriter, r *http.Request) {
	_, c, client, ok := h.admit(w, r)
	if !ok {
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"client_id": client.ID, "workspace": c.Workspace.Slug(), "kind": client.Kind})
}

// relativePath is the path PurePosixPath gives: empty and "." segments
// dropped; false for an absolute path, one with "..", or none.
func relativePath(p string) (string, bool) {
	if p == "" || strings.HasPrefix(p, "/") {
		return "", false
	}
	var parts []string
	for _, s := range strings.Split(p, "/") {
		switch s {
		case "", ".":
		case "..":
			return "", false
		default:
			parts = append(parts, s)
		}
	}
	if len(parts) == 0 {
		return "", false
	}
	return strings.Join(parts, "/"), true
}

func contentTypeOf(p string) string {
	t := mime.TypeByExtension(path.Ext(p))
	if t == "" {
		return "application/octet-stream"
	}
	if mt, _, err := mime.ParseMediaType(t); err == nil {
		return mt
	}
	return t
}

// upload is upload_task_file: a file the CLI made, into its task's folder.
func (h *handlers) upload(w http.ResponseWriter, r *http.Request) {
	p, c, _, ok := h.admit(w, r)
	if !ok {
		return
	}
	ctx := r.Context()
	rawTask := chi.URLParam(r, "task_id")
	taskID, fe := httpx.ValidateUUID(rawTask, "path", "task_id")
	if fe != nil {
		h.errs.Write(w, r, httpx.Validation(*fe))
		return
	}
	task, err := h.d.Tasks.Task(ctx, c.Workspace, taskID)
	if err != nil && !errors.Is(err, store.ErrTaskNotFound) {
		h.errs.Write(w, r, err)
		return
	}
	if owner, _ := task.Metadata[runnerClientKey].(string); err != nil || owner != p.BoundClientID {
		h.errs.Write(w, r, httpx.NotFound(detailNoTask))
		return
	}
	prefix := "/v1/runner/tasks/" + rawTask + "/files/"
	filePath, ok := relativePath(strings.TrimPrefix(r.URL.Path, prefix))
	if !strings.HasPrefix(r.URL.Path, prefix) || !ok {
		h.errs.Write(w, r, httpx.HTTPError(http.StatusUnprocessableEntity, detailRelative))
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, fileMaxBytes+1))
	if err != nil {
		h.errs.Write(w, r, err)
		return
	}
	if len(body) > fileMaxBytes {
		h.errs.Write(w, r, httpx.HTTPError(http.StatusRequestEntityTooLarge, detailTooLarge))
		return
	}
	key := "harness-files/" + c.Workspace.ID() + "/" + taskID + "/" + filePath
	if err := h.d.Files.Put(ctx, key, bytes.NewReader(body), int64(len(body)), blob.PutOptions{ContentType: contentTypeOf(filePath)}); err != nil {
		h.errs.Write(w, r, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// connect is connect_runner: only a client's runner key, as Authorization:
// Bearer, opens the socket, for that client. A refused socket is never
// upgraded: the runner sees 403.
func (h *handlers) connect(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	refuse := func() { http.Error(w, "", http.StatusForbidden) }
	token, ok := authn.BearerToken(r)
	if !ok {
		refuse()
		return
	}
	p, err := h.d.Gate.RunnerKey(ctx, token)
	if err != nil {
		h.errs.Write(w, r, err)
		return
	}
	if p == nil {
		refuse()
		return
	}
	client, found, err := h.runnerClient(ctx, *p)
	if err != nil {
		h.errs.Write(w, r, err)
		return
	}
	if !found || !client.Runner {
		h.d.Log.Warn("Refused the runner socket of a client gone or not a runner's kind", "client_id", p.BoundClientID)
		refuse()
		return
	}
	slug, err := h.d.Slugs.Slug(ctx, client.WorkspaceID)
	if err != nil {
		h.errs.Write(w, r, err)
		return
	}
	ws, err := scope.NewWorkspace(client.WorkspaceID, slug)
	if err != nil {
		h.errs.Write(w, r, err)
		return
	}
	caller, err := h.d.Gate.EnterAsRunner(*p, ws)
	if err != nil {
		h.errs.Write(w, r, err)
		return
	}
	// The runner is no browser: it authenticates with its key, never a cookie.
	sock, err := websocket.Accept(w, r, &websocket.AcceptOptions{InsecureSkipVerify: true})
	if err != nil {
		h.d.Log.Warn("Runner socket upgrade failed", "client_id", client.ID, "error", err.Error())
		return
	}
	newConn(h.d, sock, client, caller).serve(ctx)
}
