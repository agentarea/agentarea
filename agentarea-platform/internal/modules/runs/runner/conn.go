package runner

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"regexp"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/coder/websocket"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/workflows"
)

const (
	runnerClientKey  = "runner_client_id"
	workspaceTaskKey = "workspace_task_id"
	runnerSessionKey = "runner_session_id"
	modelParameter   = "model"
	effortParameter  = "reasoning_effort"
	eventSource      = "agentarea-worker"
)

func effortShape() *regexp.Regexp { return regexp.MustCompile(`^[a-z][a-z_-]{0,15}$`) }

var (
	errDisconnected = errors.New("the runner disconnected")
	errLeaseExpired = errors.New("the runner sent nothing within its lease")
)

type readResult struct {
	data []byte
	err  error
}

// conn is RunnerConnection: one runner's socket, the turns it holds and the
// frames both ways. Frames from the runner are handled in order on one
// goroutine; deliveries, updates and the client's turn worker run beside it.
type conn struct {
	d      *Deps
	ws     *websocket.Conn
	client agentsapi.RunnerClient
	caller authn.Caller
	log    *slog.Logger
	ctx    context.Context

	capacity int
	msgs     chan readResult
	closed   atomic.Bool
	sendMu   sync.Mutex
	mu       sync.Mutex
	turns    map[string]*turn
}

// turn is _Turn: a turn this socket's runner holds, and what it reported
// that the run has not heard.
type turn struct {
	id    string
	call  workflows.RunnerTurnCall
	actor workflows.RunnerActor

	done     chan struct{}
	once     sync.Once
	finished *upFrame
	lost     bool

	mu             sync.Mutex
	events         []workflows.RunnerTurnEvent
	approvals      []workflows.RunnerApprovalAsk
	steers         []workflows.RunnerSteerOutcome
	signalledActor bool
	live           *liveSnapshots

	sig sync.Mutex
}

func (t *turn) end(f *upFrame, lost bool) {
	t.once.Do(func() {
		t.finished, t.lost = f, lost
		close(t.done)
	})
}

func (t *turn) pendingLocked() bool {
	return len(t.events) > 0 || len(t.approvals) > 0 || len(t.steers) > 0 || !t.signalledActor
}

func (t *turn) pending() bool {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.pendingLocked()
}

func (t *turn) unheard() int {
	t.mu.Lock()
	defer t.mu.Unlock()
	return len(t.events) + len(t.approvals) + len(t.steers)
}

func newConn(d *Deps, ws *websocket.Conn, client agentsapi.RunnerClient, caller authn.Caller) *conn {
	ws.SetReadLimit(4*frameMaxChars + 64)
	return &conn{
		d: d, ws: ws, client: client, caller: caller, capacity: 1,
		log:   d.Log.With("client_id", client.ID),
		msgs:  make(chan readResult),
		turns: map[string]*turn{},
	}
}

func (c *conn) readLoop(ctx context.Context) {
	defer close(c.msgs)
	for {
		typ, data, err := c.ws.Read(ctx)
		if err != nil {
			return
		}
		r := readResult{data: data}
		if typ != websocket.MessageText {
			r = readResult{err: badFrame("a binary frame")}
		}
		select {
		case c.msgs <- r:
		case <-ctx.Done():
			return
		}
		if r.err != nil {
			return
		}
	}
}

func (c *conn) next(ctx context.Context, timeout time.Duration) ([]byte, error) {
	t := time.NewTimer(timeout)
	defer t.Stop()
	select {
	case r, ok := <-c.msgs:
		if !ok {
			return nil, errDisconnected
		}
		return r.data, r.err
	case <-t.C:
		return nil, errLeaseExpired
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

func (c *conn) send(frame map[string]any) error {
	b, err := json.Marshal(frame)
	if err != nil {
		return err
	}
	c.sendMu.Lock()
	defer c.sendMu.Unlock()
	return c.ws.Write(c.ctx, websocket.MessageText, b)
}

func (c *conn) close(code websocket.StatusCode) {
	if err := c.ws.Close(code, ""); err != nil {
		c.log.Debug("Runner socket close", "code", int(code), "error", err.Error())
	}
}

type ended struct {
	what string
	err  error
}

// serve is RunnerConnection.serve: hello, then the turn worker, the frames,
// the deliveries and the updates until one of them ends.
func (c *conn) serve(parent context.Context) {
	ctx, cancel := context.WithCancel(parent)
	defer cancel()
	c.ctx = ctx
	go c.readLoop(ctx)
	raw, err := c.next(ctx, helloTimeout)
	var hello *upFrame
	if err == nil {
		hello, err = parseUpFrame(raw)
	}
	if err != nil {
		c.log.Warn("Runner sent no hello", "error", err.Error())
		c.close(websocket.StatusPolicyViolation)
		return
	}
	if hello.Type != "hello" {
		c.log.Warn("Runner began with another frame", "type", hello.Type)
		c.close(websocket.StatusPolicyViolation)
		return
	}
	if err := c.onHello(ctx, hello); err != nil {
		c.log.Error("Runner hello failed", "error", err.Error())
		c.close(websocket.StatusInternalError)
		return
	}
	worker := c.d.Workers.NewWorker(api.RunnerTaskQueue(c.client.ID), durable.Limits{
		MaxActivities: c.capacity, ActivityPollers: min(c.capacity, 5), MaxWorkflows: 2, WorkflowPollers: 2,
	})
	c.d.register(worker, c, c.d.Workers.Executor())
	wctx, stopWorker := context.WithCancel(context.WithoutCancel(ctx))
	defer stopWorker()
	done := make(chan ended, 4)
	go func() { done <- ended{"frames", c.frames(ctx)} }()
	go func() { done <- ended{"the worker polling its turns", workerRun(wctx, worker)} }()
	go func() { done <- ended{"the deliveries", c.listen(ctx)} }()
	go func() { done <- ended{"the updates", c.sendUpdates(ctx)} }()
	first := <-done
	if first.what == "frames" {
		c.framesEnded(first.err)
	} else {
		c.log.Error("Runner socket lost a part; closing it", "part", first.what, "error", fmt.Sprint(first.err))
		c.close(websocket.StatusInternalError)
	}
	c.closed.Store(true)
	c.mu.Lock()
	for _, t := range c.turns {
		t.end(nil, true)
	}
	c.mu.Unlock()
	cancel()
	stopWorker()
	for range 3 {
		if e := <-done; e.err != nil && !errors.Is(e.err, context.Canceled) && e.what != "frames" {
			c.log.Error("Runner socket part ended with an error", "part", e.what, "error", e.err.Error())
		}
	}
	_ = c.ws.CloseNow()
}

func workerRun(ctx context.Context, w durable.Worker) error {
	if err := w.Run(ctx); err != nil {
		return err
	}
	if ctx.Err() == nil {
		return errors.New("the worker stopped polling")
	}
	return nil
}

func (c *conn) frames(ctx context.Context) error {
	for {
		raw, err := c.next(ctx, lease)
		if err != nil {
			return err
		}
		f, err := parseUpFrame(raw)
		if err != nil {
			return err
		}
		if err := c.handle(ctx, f); err != nil {
			return err
		}
	}
}

func (c *conn) framesEnded(err error) {
	var pe *protocolError
	switch {
	case errors.Is(err, errDisconnected):
		c.mu.Lock()
		held := len(c.turns)
		c.mu.Unlock()
		c.log.Info("Runner disconnected", "turns", held)
	case errors.Is(err, errLeaseExpired):
		c.log.Warn("Runner sent nothing within its lease; closing its socket", "seconds", leaseSeconds)
		c.close(websocket.StatusGoingAway)
	case errors.As(err, &pe):
		c.log.Error("Runner sent a bad frame", "error", err.Error())
		c.close(websocket.StatusUnsupportedData)
	case errors.Is(err, context.Canceled):
	default:
		c.log.Error("Runner socket failed", "error", fmt.Sprint(err))
		c.close(websocket.StatusInternalError)
	}
}

func (c *conn) onHello(ctx context.Context, f *upFrame) error {
	c.capacity = *f.Capacity
	var models []agentsapi.RunnerModel
	if f.Models != nil {
		models = make([]agentsapi.RunnerModel, 0, len(*f.Models))
		for _, m := range *f.Models {
			levels := []string{}
			if m.ReasoningLevels != nil {
				levels = *m.ReasoningLevels
			}
			models = append(models, agentsapi.RunnerModel{Name: *m.Name, ReasoningLevels: levels, DefaultReasoning: m.DefaultReasoning})
		}
	}
	if err := c.d.Clients.RecordHello(ctx, c.caller.Workspace, c.client.ID, models, deref(f.DefaultModel)); err != nil {
		return err
	}
	if err := c.d.Presence.Mark(ctx, c.client.ID); err != nil {
		return err
	}
	if len(f.Turns) > 0 {
		c.log.Warn("Runner reconnected still running turns; their runs assign them again", "turns", len(f.Turns))
	}
	if err := c.send(map[string]any{
		"type": "welcome", "client_id": c.client.ID, "workspace": c.caller.Workspace.Slug(), "kind": c.client.Kind,
		"ping_seconds": pingSeconds, "lease_seconds": leaseSeconds, "turns": []string{},
	}); err != nil {
		return err
	}
	c.log.Info("Runner connected", "capacity", c.capacity, "version", deref(f.Version))
	return nil
}

func (c *conn) held(turnID string) *turn {
	id, err := uuid.Parse(turnID)
	if err != nil {
		return nil
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.turns[id.String()]
}

func (c *conn) handle(ctx context.Context, f *upFrame) error {
	switch f.Type {
	case "ping":
		return c.d.Presence.Mark(ctx, c.client.ID)
	case "hello":
		return badFrame("hello sent twice")
	}
	t := c.held(*f.TurnID)
	if t == nil {
		c.log.Warn("Runner sent a frame for a turn it does not hold", "type", f.Type, "turn_id", *f.TurnID)
		return nil
	}
	if t.unheard() >= turnPendingMax {
		return badFrame("turn %s reported more than the run has heard", t.call.Request.TurnKey)
	}
	switch f.Type {
	case "turn.started":
		c.keepSession(ctx, t, *f.SessionID)
	case "turn.event":
		c.onEvent(ctx, t, f)
	case "approval.request":
		args := f.args
		t.mu.Lock()
		t.approvals = append(t.approvals, workflows.RunnerApprovalAsk{
			RequestID: *f.RequestID, ItemID: deref(f.ItemID), Kind: *f.Kind, ToolName: *f.ToolName,
			Arguments: args, Reason: deref(f.Reason),
		})
		t.mu.Unlock()
		if err := c.signal(ctx, t); err != nil {
			c.log.Error("Could not signal the run the approval its turn asks for; trying again",
				"workflow_id", t.call.WorkflowID, "turn_key", t.call.Request.TurnKey, "error", err.Error())
		}
	case "steer.accepted", "steer.rejected":
		t.mu.Lock()
		t.steers = append(t.steers, workflows.RunnerSteerOutcome{MessageID: *f.MessageID, Accepted: f.Type == "steer.accepted"})
		t.mu.Unlock()
	case "turn.finished":
		if f.SessionID != nil && *f.SessionID != "" {
			c.keepSession(ctx, t, *f.SessionID)
		}
		t.end(f, false)
	}
	return nil
}

// keepSession keeps the CLI's session on the task, so every later turn resumes it.
func (c *conn) keepSession(ctx context.Context, t *turn, sessionID string) {
	if err := c.d.Tasks.KeepSession(ctx, c.caller.Workspace, t.call.Request.TaskID, sessionID); err != nil {
		c.log.Error("Could not keep the CLI session of the turn on its task",
			"turn_key", t.call.Request.TurnKey, "task_id", t.call.Request.TaskID, "error", err.Error())
	}
}

func (c *conn) onEvent(ctx context.Context, t *turn, f *upFrame) {
	b := f.body
	t.mu.Lock()
	switch b.Kind {
	case "message.delta":
		channel := "text"
		if b.Channel != nil {
			channel = *b.Channel
		}
		text, thinking, due := t.live.addText(*b.ItemID, *b.Text, channel)
		t.mu.Unlock()
		if due {
			c.broadcast(ctx, t, domain.EventLLMChunk, map[string]any{
				"execution_id": t.call.WorkflowID, "iteration": t.call.Request.Iteration, "item_id": *b.ItemID,
				"chunk": text, "thinking": thinking, "chunk_index": *f.Seq, "is_final": false, "chunk_type": channel,
			})
		}
		return
	case "tool.progress":
		output, due := t.live.addOutput(*b.ID, *b.Output)
		t.mu.Unlock()
		if due {
			c.broadcast(ctx, t, domain.EventToolProgress, map[string]any{
				"tool_name": *b.Name, "tool_call_id": *b.ID, "message": output,
			})
		}
		return
	case "message":
		t.events = append(t.events, workflows.RunnerTurnEvent{
			Seq: *f.Seq, Kind: "message", ItemID: *b.ItemID, Text: taskRelative(*b.Text, t.call.Request.TaskID), Model: deref(b.Model),
		})
		t.live.forget(*b.ItemID)
	case "tool.call":
		t.events = append(t.events, workflows.RunnerTurnEvent{
			Seq: *f.Seq, Kind: "tool.call", ItemID: *b.ID, Name: *b.Name, Arguments: b.args,
		})
	case "tool.result":
		success := true
		if b.Success != nil {
			success = *b.Success
		}
		t.events = append(t.events, workflows.RunnerTurnEvent{
			Seq: *f.Seq, Kind: "tool.result", ItemID: *b.ID, Name: *b.Name, Output: clipped(deref(b.Output)),
			Success: &success, ExitCode: b.ExitCode,
		})
		t.live.forget(*b.ID)
	}
	t.mu.Unlock()
}

func (c *conn) broadcast(ctx context.Context, t *turn, eventType string, data map[string]any) {
	data["task_id"] = t.call.Request.TaskID
	e := events.IntegrationEvent{
		ID: uuid.NewString(), Type: eventType, Source: eventSource, Subject: t.call.Request.TaskID,
		Time: c.d.Now().UTC(), Data: data, Extensions: map[string]string{"workspace": c.caller.Workspace.ID()},
	}
	if err := (service.BrokerEvents{Broker: c.d.Broker}).Broadcast(ctx, e); err != nil {
		c.log.Error("Could not broadcast a live event of the turn", "type", eventType, "turn_key", t.call.Request.TurnKey, "error", err.Error())
	}
}

// signal tells the turn's run what the runner reported since the last time.
func (c *conn) signal(ctx context.Context, t *turn) error {
	t.sig.Lock()
	defer t.sig.Unlock()
	for {
		t.mu.Lock()
		if !t.pendingLocked() {
			t.mu.Unlock()
			return nil
		}
		actor := t.actor
		u := workflows.RunnerTurnUpdate{
			TurnKey:   t.call.Request.TurnKey,
			Actor:     &actor,
			Events:    append([]workflows.RunnerTurnEvent{}, signalBatch(t.events)...),
			Approvals: append([]workflows.RunnerApprovalAsk{}, t.approvals...),
			Steers:    append([]workflows.RunnerSteerOutcome{}, t.steers...),
		}
		t.mu.Unlock()
		if err := t.call.Signal(ctx, u); err != nil {
			return err
		}
		t.mu.Lock()
		t.events = t.events[len(u.Events):]
		t.approvals = t.approvals[len(u.Approvals):]
		t.steers = t.steers[len(u.Steers):]
		t.signalledActor = true
		t.mu.Unlock()
	}
}

func (c *conn) sendUpdates(ctx context.Context) error {
	tick := time.NewTicker(updateEvery)
	defer tick.Stop()
	for {
		select {
		case <-ctx.Done():
			return nil
		case <-tick.C:
		}
		c.mu.Lock()
		held := make([]*turn, 0, len(c.turns))
		for _, t := range c.turns {
			held = append(held, t)
		}
		c.mu.Unlock()
		for _, t := range held {
			if !t.pending() {
				continue
			}
			if err := c.signal(ctx, t); err != nil && ctx.Err() == nil {
				c.log.Error("Could not signal the run what its turn did; trying again",
					"workflow_id", t.call.WorkflowID, "turn_key", t.call.Request.TurnKey, "error", err.Error())
			}
		}
	}
}

// listen relays the client's deliveries for the turns this socket holds.
func (c *conn) listen(ctx context.Context) error {
	live, err := c.d.Broker.OpenLive(ctx)
	if err != nil {
		return err
	}
	defer func() { _ = live.Close() }()
	if err := live.Subscribe(ctx, "clients."+c.client.ID+".runner"); err != nil {
		return err
	}
	for {
		_, fields, ok, err := live.Next(ctx, deliveryPoll)
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return err
		}
		if ok {
			if err := c.onDelivery(fields); err != nil {
				return err
			}
		}
	}
}

func field(fields map[string]string, key string) (string, error) {
	v, ok := fields[key]
	if !ok {
		return "", fmt.Errorf("a runner delivery has no %s", key)
	}
	return v, nil
}

func (c *conn) onDelivery(fields map[string]string) error {
	taskID, err := field(fields, "task_id")
	if err != nil {
		return err
	}
	turnKey, err := field(fields, "turn_key")
	if err != nil {
		return err
	}
	var t *turn
	c.mu.Lock()
	for _, h := range c.turns {
		if h.call.Request.TaskID == taskID && h.call.Request.TurnKey == turnKey {
			t = h
			break
		}
	}
	c.mu.Unlock()
	if t == nil {
		return nil
	}
	kind, err := field(fields, "kind")
	if err != nil {
		return err
	}
	switch kind {
	case "steer":
		messageID, err := field(fields, "message_id")
		if err != nil {
			return err
		}
		text, err := field(fields, "text")
		if err != nil {
			return err
		}
		return c.send(map[string]any{"type": "turn.steer", "turn_id": t.id, "message_id": messageID, "text": text})
	case "pause":
		return c.send(map[string]any{"type": "turn.cancel", "turn_id": t.id})
	case "decision":
		requestID, err := field(fields, "request_id")
		if err != nil {
			return err
		}
		approved, err := field(fields, "approved")
		if err != nil {
			return err
		}
		return c.send(map[string]any{"type": "approval.decision", "turn_id": t.id, "request_id": requestID, "approved": approved == "true"})
	}
	return fmt.Errorf("unknown delivery %q to a runner", kind)
}

func lostError() error {
	return &durable.ApplicationError{Type: workflows.RunnerLostType, Message: "the runner went away"}
}

func nonRetryable(errType, msg string) error {
	return &durable.ApplicationError{Type: errType, Message: msg, NonRetryable: true}
}

// RunTurn is run_runner_turn: one turn of a task on this socket's runner,
// until the runner finishes it.
func (c *conn) RunTurn(ctx context.Context, call workflows.RunnerTurnCall) (workflows.RunnerTurnResult, error) {
	if c.closed.Load() {
		return workflows.RunnerTurnResult{}, lostError()
	}
	assign, actor, onBehalfOf, err := c.assignment(ctx, call.Request)
	if err != nil {
		return workflows.RunnerTurnResult{}, err
	}
	t := &turn{id: uuid.NewString(), call: call, actor: actor, done: make(chan struct{}), live: newLiveSnapshots(c.d.Now)}
	token, err := c.d.Tokens.Issue(authn.TurnClaims{
		TurnID: t.id, TaskID: call.Request.TaskID, WorkspaceID: call.Request.WorkspaceID, ClientID: c.client.ID,
		ActorType: authn.SubjectKind(actor.Type), ActorID: actor.ID, OnBehalfOf: onBehalfOf,
	}, turnTimeout)
	if err != nil {
		return workflows.RunnerTurnResult{}, err
	}
	if err := c.d.Live.Begin(ctx, t.id, lease); err != nil {
		return workflows.RunnerTurnResult{}, err
	}
	c.mu.Lock()
	c.turns[t.id] = t
	c.mu.Unlock()
	c.log.Info("Turn assigned to the runner", "turn_key", call.Request.TurnKey, "task_id", call.Request.TaskID)
	defer func() {
		c.mu.Lock()
		delete(c.turns, t.id)
		c.mu.Unlock()
		if err := c.d.Live.End(context.WithoutCancel(ctx), t.id); err != nil {
			c.log.Error("Could not end the lease of the turn", "turn_key", call.Request.TurnKey, "error", err.Error())
		}
	}()
	assign["type"], assign["turn_id"], assign["token"], assign["mcp_path"] = "turn.assign", t.id, token, "/mcp/clients/"+c.client.ID
	if err := c.send(assign); err != nil {
		return c.failed(ctx, t, err)
	}
	tick := time.NewTicker(heartbeatEvery)
	defer tick.Stop()
	for {
		select {
		case <-t.done:
			if t.lost {
				c.reportLost(ctx, t)
				return workflows.RunnerTurnResult{}, lostError()
			}
			if err := c.report(ctx, t); err != nil {
				return c.failed(ctx, t, err)
			}
			f := t.finished
			return workflows.RunnerTurnResult{Status: *f.Status, Response: taskRelative(deref(f.Response), call.Request.TaskID), Error: deref(f.Error)}, nil
		case <-ctx.Done():
			if c.closed.Load() {
				c.reportLost(ctx, t)
				return workflows.RunnerTurnResult{}, lostError()
			}
			c.stop(ctx, t)
			return workflows.RunnerTurnResult{}, ctx.Err()
		case <-tick.C:
			call.Heartbeat()
			if err := c.d.Live.Renew(ctx, t.id, lease); err != nil {
				c.log.Error("Could not renew the lease of the turn; trying again", "turn_key", call.Request.TurnKey, "error", err.Error())
			}
		}
	}
}

// failed: a lost socket fails the turn as lost; anything else stops the CLI's turn.
func (c *conn) failed(ctx context.Context, t *turn, err error) (workflows.RunnerTurnResult, error) {
	if c.closed.Load() {
		c.log.Warn("Runner went away handing over the turn", "turn_key", t.call.Request.TurnKey, "error", err.Error())
		c.reportLost(ctx, t)
		return workflows.RunnerTurnResult{}, lostError()
	}
	c.log.Error("Turn failed on the platform; stopping the CLI's turn", "turn_key", t.call.Request.TurnKey, "error", err.Error())
	c.cancelOnRunner(t)
	return workflows.RunnerTurnResult{}, err
}

// report signals the turn's last report, tried again: a turn its run never heard is lost.
func (c *conn) report(ctx context.Context, t *turn) error {
	for attempt := 1; ; attempt++ {
		err := c.signal(ctx, t)
		if err == nil {
			return nil
		}
		if attempt == finalAttempts {
			return err
		}
		c.log.Warn("Could not signal the run the end of the turn; trying again", "workflow_id", t.call.WorkflowID,
			"turn_key", t.call.Request.TurnKey, "error", err.Error())
		t.call.Heartbeat()
		select {
		case <-time.After(heartbeatEvery):
		case <-ctx.Done():
			return ctx.Err()
		}
	}
}

func (c *conn) reportLost(ctx context.Context, t *turn) {
	sctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), stopGrace)
	defer cancel()
	if err := c.signal(sctx, t); err != nil {
		c.log.Error("Could not signal the run what the turn did before its runner went away",
			"workflow_id", t.call.WorkflowID, "turn_key", t.call.Request.TurnKey, "error", err.Error())
	}
}

func (c *conn) cancelOnRunner(t *turn) {
	if err := c.send(map[string]any{"type": "turn.cancel", "turn_id": t.id}); err != nil {
		c.log.Error("Could not tell the runner to stop the turn", "turn_key", t.call.Request.TurnKey, "error", err.Error())
	}
}

// stop: the run was stopped; stop the CLI's turn and record what it did until then.
func (c *conn) stop(ctx context.Context, t *turn) {
	c.cancelOnRunner(t)
	select {
	case <-t.done:
		if t.lost {
			c.log.Warn("Runner did not confirm stopping the turn", "turn_key", t.call.Request.TurnKey)
		}
	case <-time.After(stopGrace):
		c.log.Warn("Runner did not confirm stopping the turn", "turn_key", t.call.Request.TurnKey)
	}
	sctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), time.Duration(finalAttempts)*heartbeatEvery+stopGrace)
	defer cancel()
	if err := c.report(sctx, t); err != nil {
		c.log.Error("The run never heard what the stopped turn did", "workflow_id", t.call.WorkflowID,
			"turn_key", t.call.Request.TurnKey, "error", err.Error())
	}
}

// assignment is _assignment: the turn as the runner needs it, its actor and
// the person the task is attributed to.
func (c *conn) assignment(ctx context.Context, req workflows.RunnerTurnRequest) (map[string]any, workflows.RunnerActor, string, error) {
	ws := c.caller.Workspace
	if _, err := uuid.Parse(req.TaskID); err != nil {
		return nil, workflows.RunnerActor{}, "", nonRetryable("TaskNotFound", fmt.Sprintf("task %s not found", req.TaskID))
	}
	task, err := c.d.Tasks.Task(ctx, ws, req.TaskID)
	if errors.Is(err, store.ErrTaskNotFound) {
		return nil, workflows.RunnerActor{}, "", nonRetryable("TaskNotFound", fmt.Sprintf("task %s not found", req.TaskID))
	}
	if err != nil {
		return nil, workflows.RunnerActor{}, "", err
	}
	if owner, _ := task.Metadata[runnerClientKey].(string); owner != c.client.ID {
		return nil, workflows.RunnerActor{}, "", nonRetryable("WrongClient", fmt.Sprintf("task %s does not run on client %s", req.TaskID, c.client.ID))
	}
	agent, err := c.d.Clients.Agent(ctx, ws, task.AgentID)
	if errors.Is(err, agentsapi.ErrNotFound) {
		return nil, workflows.RunnerActor{}, "", nonRetryable("TaskNotFound", fmt.Sprintf("agent or client of task %s not found", req.TaskID))
	}
	if err != nil {
		return nil, workflows.RunnerActor{}, "", err
	}
	client, ok, err := c.d.Clients.Client(ctx, ws, c.client.ID)
	if err != nil {
		return nil, workflows.RunnerActor{}, "", err
	}
	if !ok {
		return nil, workflows.RunnerActor{}, "", nonRetryable("TaskNotFound", fmt.Sprintf("agent or client of task %s not found", req.TaskID))
	}
	model := client.DefaultModel
	if m, ok := task.Parameters[modelParameter].(string); ok && m != "" {
		model = m
	}
	effort, err := reasoningEffort(task.Parameters[effortParameter])
	if err != nil {
		return nil, workflows.RunnerActor{}, "", err
	}
	if effort == "" {
		effort = agent.ReasoningEffort
	}
	actor := actorOfTask(task.SourceIdentity, task.AgentID)
	if req.Actor != nil {
		actor = *req.Actor
	}
	requestedBy := task.CreatedBy
	if actor.Type == string(authn.SubjectUser) {
		requestedBy = actor.ID
	}
	domains := client.AllowDomains
	if domains == nil {
		domains = []string{}
	}
	return map[string]any{
		"task_id": task.ID, "agent_id": task.AgentID, "iteration": req.Iteration, "message": req.Message,
		"session_id": task.Metadata[runnerSessionKey], "requested_by": requestedBy,
		"actor": map[string]any{"type": actor.Type, "id": actor.ID},
		"model": nullable(model), "reasoning_effort": nullable(effort), "instructions": withOutputsLimit(agent.Instructions),
		"allow_domains": domains, "sandbox": client.Sandbox,
	}, actor, task.CreatedBy, nil
}

func nullable(s string) any {
	if s == "" {
		return nil
	}
	return s
}

// reasoningEffort is reasoning_effort_of over the task's parameter.
func reasoningEffort(v any) (string, error) {
	if v == nil || v == "" {
		return "", nil
	}
	s, ok := v.(string)
	if !ok || !effortShape().MatchString(s) {
		return "", errors.New("reasoning_effort must be a level name such as low or high")
	}
	return s, nil
}

// actorOfTask is actor_of_task: the person who started the task, else its agent.
func actorOfTask(sourceIdentity, agentID string) workflows.RunnerActor {
	if id, ok := strings.CutPrefix(sourceIdentity, "user:"); ok {
		return workflows.RunnerActor{Type: string(authn.SubjectUser), ID: id}
	}
	return workflows.RunnerActor{Type: string(authn.SubjectAgent), ID: agentID}
}
