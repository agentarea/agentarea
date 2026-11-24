package service

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strconv"
	"sync"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
)

const (
	snapshotBatchSize = 500
	feedMaxWallTime   = 30 * time.Minute
	hubTailBlock      = 5 * time.Second
)

// Envelope is TaskEventEnvelope: one event of a task's feed.
type Envelope struct {
	EventType string
	EventID   string
	// Timestamp is nil when the event carries no time.
	Timestamp any
	Data      wirejson.Object
	Seq       *int64
}

var errHubClosed = errors.New("runs: the task events hub has shut down")

// taskHub is TaskEventsHub: one tail of tasks.events and one live
// connection for the process, fanned out to each task's subscribers. Its
// loops start on the first subscribe and end when Run's context does.
type taskHub struct {
	broker events.Broker
	log    *slog.Logger
	ctx    context.Context
	cancel context.CancelFunc
	loops  sync.WaitGroup

	mu      sync.Mutex
	started bool
	closed  bool
	live    events.LiveChannels
	queues  map[string]map[*subscription]bool
}

type subscription struct {
	mu     sync.Mutex
	items  []Envelope
	notify chan struct{}
	ended  chan struct{}
}

func (s *subscription) put(e Envelope) {
	s.mu.Lock()
	s.items = append(s.items, e)
	s.mu.Unlock()
	select {
	case s.notify <- struct{}{}:
	default:
	}
}

// get waits for the next envelope; ok false when ctx ends or the hub stops.
func (s *subscription) get(ctx context.Context) (Envelope, bool) {
	for {
		s.mu.Lock()
		if len(s.items) > 0 {
			e := s.items[0]
			s.items = s.items[1:]
			s.mu.Unlock()
			return e, true
		}
		s.mu.Unlock()
		select {
		case <-ctx.Done():
			return Envelope{}, false
		case <-s.ended:
			return Envelope{}, false
		case <-s.notify:
		}
	}
}

func newTaskHub(b events.Broker, log *slog.Logger) *taskHub {
	ctx, cancel := context.WithCancel(context.Background())
	return &taskHub{broker: b, log: log, ctx: ctx, cancel: cancel, queues: map[string]map[*subscription]bool{}}
}

// Run holds the hub open until ctx ends, then stops its loops, ends every
// subscription and closes the live connection; later subscribes fail.
func (h *taskHub) Run(ctx context.Context) error {
	<-ctx.Done()
	h.mu.Lock()
	h.closed = true
	h.cancel()
	for _, qs := range h.queues {
		for s := range qs {
			close(s.ended)
		}
	}
	h.queues = map[string]map[*subscription]bool{}
	live := h.live
	h.mu.Unlock()
	h.loops.Wait()
	if live == nil {
		return nil
	}
	return live.Close()
}

// RunStreamHub holds the task events hub open until ctx ends.
func (s *Surface) RunStreamHub(ctx context.Context) error { return s.hub.Run(ctx) }

// subscribe registers a queue for taskID, starting the hub on first use.
func (h *taskHub) subscribe(ctx context.Context, taskID string) (*subscription, func(), error) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.closed {
		return nil, nil, errHubClosed
	}
	if err := h.start(ctx); err != nil {
		return nil, nil, err
	}
	sub := &subscription{notify: make(chan struct{}, 1), ended: make(chan struct{})}
	first := h.queues[taskID] == nil
	if first {
		h.queues[taskID] = map[*subscription]bool{}
	}
	h.queues[taskID][sub] = true
	if first {
		if err := h.live.Subscribe(ctx, events.TaskLiveChannel(taskID)); err != nil {
			delete(h.queues, taskID)
			return nil, nil, err
		}
	}
	return sub, func() {
		h.mu.Lock()
		defer h.mu.Unlock()
		if h.closed {
			return
		}
		qs := h.queues[taskID]
		delete(qs, sub)
		if len(qs) == 0 {
			delete(h.queues, taskID)
			if err := h.live.Unsubscribe(context.WithoutCancel(ctx), events.TaskLiveChannel(taskID)); err != nil {
				h.log.Error("Failed to leave a task's live channel", "task_id", taskID, "error", err.Error())
			}
		}
	}, nil
}

func (h *taskHub) start(ctx context.Context) error {
	if h.started {
		return nil
	}
	cursor, err := h.broker.LastID(ctx, events.TaskEvents)
	if err != nil {
		return err
	}
	live, err := h.broker.OpenLive(h.ctx)
	if err != nil {
		return err
	}
	h.live, h.started = live, true
	h.loops.Add(2)
	go func() {
		defer h.loops.Done()
		h.runTail(h.ctx, cursor)
	}()
	go func() {
		defer h.loops.Done()
		h.runLive(h.ctx, live)
	}()
	return nil
}

// retryWait waits d before a retry; false when ctx ended first.
func retryWait(ctx context.Context, d time.Duration) bool {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-t.C:
		return true
	}
}

func (h *taskHub) runTail(ctx context.Context, cursor string) {
	for ctx.Err() == nil {
		next, msgs, err := h.broker.Tail(ctx, events.TaskEvents, cursor, hubTailBlock, 500)
		if ctx.Err() != nil {
			return
		}
		if err != nil {
			h.log.Error("Tail of tasks.events failed; retrying", "error", err.Error())
			if !retryWait(ctx, time.Second) {
				return
			}
			continue
		}
		cursor = next
		for _, m := range msgs {
			e, err := events.Decode(m.Fields)
			if err != nil {
				h.log.Error("Undecodable entry on tasks.events; skipped", "message_id", m.ID, "error", err.Error())
				continue
			}
			h.dispatch(e)
		}
	}
}

func (h *taskHub) runLive(ctx context.Context, live events.LiveChannels) {
	for ctx.Err() == nil {
		channel, fields, ok, err := live.Next(ctx, time.Second)
		if ctx.Err() != nil {
			return
		}
		if err != nil {
			h.log.Error("Live task signals failed; retrying", "error", err.Error())
			if !retryWait(ctx, time.Second) {
				return
			}
			continue
		}
		if !ok {
			continue
		}
		e, err := events.Decode(fields)
		if err != nil {
			h.log.Error("Undecodable live signal; skipped", "channel", channel, "error", err.Error())
			continue
		}
		h.dispatch(e)
	}
}

func (h *taskHub) dispatch(e events.IntegrationEvent) {
	h.mu.Lock()
	qs := h.queues[e.Subject]
	subs := make([]*subscription, 0, len(qs))
	for s := range qs {
		subs = append(subs, s)
	}
	h.mu.Unlock()
	if len(subs) == 0 {
		return
	}
	env, err := envelopeFromEvent(e)
	if err != nil {
		h.log.Error("Task event with a bad seq; skipped", "event_id", e.ID, "error", err.Error())
		return
	}
	for _, s := range subs {
		s.put(env)
	}
}

// envelopeFromEvent is envelope_from_event.
func envelopeFromEvent(e events.IntegrationEvent) (Envelope, error) {
	env := Envelope{EventType: e.Type, EventID: e.ID, Data: plainToObject(e.Data)}
	if !e.Time.IsZero() {
		env.Timestamp = isoWithOffset(e.Time)
	}
	if raw, ok := e.Extensions["seq"]; ok {
		n, err := strconv.ParseInt(raw, 10, 64)
		if err != nil {
			return env, err
		}
		env.Seq = &n
	}
	return env, nil
}

// isoWithOffset is datetime.isoformat of an aware time.
func isoWithOffset(t time.Time) string {
	s := t.Format("2006-01-02T15:04:05")
	if us := t.Nanosecond() / 1000; us != 0 {
		s += fmt.Sprintf(".%06d", us)
	}
	return s + t.Format("-07:00")
}

// plainToObject is a decoded event's data as an object; maps keep sorted keys.
func plainToObject(m map[string]any) wirejson.Object {
	out := wirejson.Object{}
	for k, v := range m {
		out = append(out, wirejson.Member{Key: k, Value: v})
	}
	sortMembers(out)
	return out
}

func sortMembers(o wirejson.Object) {
	for i := 1; i < len(o); i++ {
		for j := i; j > 0 && o[j].Key < o[j-1].Key; j-- {
			o[j], o[j-1] = o[j-1], o[j]
		}
	}
}

// StreamRequest is stream_task_events' parameters.
type StreamRequest struct {
	AgentID, TaskID string
	IncludeChunks   bool
	LastEventID     string
	// Follow keeps the feed open through a run that waits or settles.
	Follow bool
	// Revealed shows the caller every event, as to the run's creator;
	// Quiet leaves out the connected frame (the creation stream sent its own).
	Revealed, Quiet bool
}

// Stream is an open task event stream: its frames, then its end.
type Stream struct {
	TaskID, AgentID string
	ExecutionID     *string
	Revealed        bool
	run             func(ctx context.Context, emit func(eventType string, data wirejson.Object, id string) error) error
}

// Run writes the stream's events through emit until the feed ends.
func (st *Stream) Run(ctx context.Context, emit func(eventType string, data wirejson.Object, id string) error) error {
	return st.run(ctx, emit)
}

// ErrorFrame is the frame a stream ends with when it fails.
func (st *Stream) ErrorFrame(now time.Time) wirejson.Object {
	return wirejson.Object{
		{Key: "task_id", Value: st.TaskID}, {Key: "agent_id", Value: st.AgentID},
		{Key: "execution_id", Value: strOrNil(st.ExecutionID)}, {Key: "error", Value: "Stream error"},
		{Key: "timestamp", Value: PyISO(now, false)},
	}
}

func terminalFeedTypes(t string) bool {
	switch t {
	case domain.EventTaskCompleted, domain.EventTaskFailed, domain.EventTaskCancelled, domain.EventExecutionFinished:
		return true
	}
	return false
}

// endsFeed is _ends_feed.
func endsFeed(e Envelope, follow bool) bool {
	if !terminalFeedTypes(e.EventType) {
		return false
	}
	if !follow {
		return true
	}
	st, _ := e.Data.Get("execution_status")
	return st != "waiting" && st != "settling"
}

// OpenStream is stream_task_events up to the response: the task is checked
// before the first frame.
func (s *Surface) OpenStream(ctx context.Context, req StreamRequest) (*Stream, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	t, ok, err := s.loadTask(ctx, c.Workspace, req.TaskID)
	if err != nil {
		return nil, s.internal(ctx, "Failed to create SSE stream", err)
	}
	if !ok || t.AgentID != req.AgentID {
		return nil, notFound("Task not found")
	}
	revealed := req.Revealed
	if !revealed {
		if revealed, err = s.mayAct(ctx, c, t); err != nil {
			return nil, s.internal(ctx, "Failed to create SSE stream", err)
		}
	}
	st := &Stream{TaskID: t.ID, AgentID: t.AgentID, ExecutionID: t.ExecutionID, Revealed: revealed}
	st.run = func(ctx context.Context, emit func(string, wirejson.Object, string) error) error {
		if req.Quiet {
			return s.feed(ctx, c, t, req, revealed, s.frame(emit))
		}
		if err := emit("connected", wirejson.Object{
			{Key: "task_id", Value: t.ID}, {Key: "agent_id", Value: t.AgentID},
			{Key: "execution_id", Value: strOrNil(t.ExecutionID)},
			{Key: "message", Value: "Connected to task event stream"},
			{Key: "timestamp", Value: PyISO(s.d.Now(), false)},
		}, ""); err != nil {
			return err
		}
		return s.feed(ctx, c, t, req, revealed, s.frame(emit))
	}
	return st, nil
}

func (s *Surface) frame(emit func(string, wirejson.Object, string) error) func(Envelope) error {
	return func(env Envelope) error {
		frame := wirejson.Object{
			{Key: "event_type", Value: env.EventType}, {Key: "event_id", Value: env.EventID},
			{Key: "timestamp", Value: env.Timestamp}, {Key: "data", Value: filterDomainFields(env.Data)},
		}
		id := ""
		if env.Seq != nil {
			frame = append(frame, wirejson.Member{Key: "seq", Value: *env.Seq})
			id = strconv.FormatInt(*env.Seq, 10)
		}
		return emit(env.EventType, frame, id)
	}
}

// feed is open_task_event_feed over iter_task_event_feed.
func (s *Surface) feed(ctx context.Context, c authn.Caller, t Task, req StreamRequest, revealed bool, yield func(Envelope) error) error {
	excluded := map[string]bool{}
	if !req.IncludeChunks {
		excluded[domain.EventLLMChunk] = true
	}
	taskID, _ := parseID(t.ID)
	var resume *Envelope
	if req.LastEventID != "" {
		env, err := s.cursor(ctx, c, taskID, req.LastEventID)
		if err != nil {
			return err
		}
		if env == nil {
			s.d.Log.WarnContext(ctx, "Last-Event-ID is not a feed position of the task; replaying its history",
				"last_event_id", req.LastEventID, "task_id", t.ID)
		}
		resume = env
	}
	closed := resume != nil && endsFeed(*resume, req.Follow)
	lastSeq := int64(-1)
	if resume != nil && resume.Seq != nil {
		lastSeq = *resume.Seq
	}
	sub, leave, err := s.hub.subscribe(ctx, t.ID)
	if err != nil {
		return err
	}
	defer leave()
	position := lastSeq
	for {
		envs, n, err := s.snapshotBatch(ctx, c, taskID, position, revealed)
		if err != nil {
			return err
		}
		for _, env := range envs {
			if env.Seq != nil {
				if *env.Seq <= lastSeq {
					continue
				}
				lastSeq = *env.Seq
			}
			if excluded[env.EventType] {
				continue
			}
			if err := yield(env); err != nil {
				return err
			}
			if endsFeed(env, req.Follow) {
				closed = true
			} else if env.EventType == domain.EventTaskStarted {
				closed = false
			}
		}
		if n < snapshotBatchSize {
			break
		}
		position = lastSeq
	}
	if closed {
		open, err := s.runOpen(ctx, c, t.ID)
		if err != nil {
			return err
		}
		if !open {
			return nil
		}
	}
	wall, cancel := context.WithTimeout(ctx, feedMaxWallTime)
	defer cancel()
	for {
		env, ok := sub.get(wall)
		if !ok {
			return nil
		}
		if env.Seq != nil {
			if *env.Seq <= lastSeq {
				continue
			}
			lastSeq = *env.Seq
		}
		if excluded[env.EventType] {
			continue
		}
		if revealed && (env.EventType == domain.EventToolCall || env.EventType == domain.EventToolResult) && env.Seq != nil {
			if env, err = s.revealedLive(ctx, c, taskID, *env.Seq); err != nil {
				return err
			}
		}
		if err := yield(env); err != nil {
			return err
		}
		if endsFeed(env, req.Follow) {
			return nil
		}
	}
}

func rowEnvelope(r feedRow, b *feedBodies) (*Envelope, error) {
	typ, data, ok, err := feedEvent(r, b)
	if err != nil || !ok {
		return nil, err
	}
	seq := r.Seq
	env := &Envelope{EventType: typ, EventID: r.EventID, Data: data, Seq: &seq}
	if r.OccurredAt != nil {
		env.Timestamp = PyISO(*r.OccurredAt, true)
	}
	return env, nil
}

// cursor is _load_cursor: the feed row Last-Event-ID names, nil when it names none.
func (s *Surface) cursor(ctx context.Context, c authn.Caller, taskID pgUUID, lastEventID string) (*Envelope, error) {
	seq, err := strconv.ParseInt(lastEventID, 10, 64)
	if err != nil || seq < -1<<31 || seq > 1<<31-1 {
		return nil, nil
	}
	sess, release, err := s.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return nil, err
	}
	defer release()
	row, ok, err := feedAt(ctx, sess, taskID, seq)
	if err != nil || !ok {
		return nil, err
	}
	return rowEnvelope(row, nil)
}

// runOpen is _run_open: the task exists and has not ended.
func (s *Surface) runOpen(ctx context.Context, c authn.Caller, taskID string) (bool, error) {
	t, ok, err := s.loadTask(ctx, c.Workspace, taskID)
	return ok && !endedStatuses(t.Status), err
}

// snapshotBatch is one read of _iter_snapshot: the envelopes after position
// and the number of rows read.
func (s *Surface) snapshotBatch(ctx context.Context, c authn.Caller, taskID pgUUID, position int64, revealed bool) ([]Envelope, int, error) {
	sess, release, err := s.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return nil, 0, err
	}
	defer release()
	q := store.New(sess.Q())
	got, err := q.SurfaceFeedAfter(ctx, store.SurfaceFeedAfterParams{
		TaskID: taskID, WorkspaceID: c.Workspace.ID(), AfterSeq: int32(position), MaxRows: snapshotBatchSize,
	})
	if err != nil {
		return nil, 0, err
	}
	rows := make([]feedRow, len(got))
	for i, g := range got {
		if rows[i], err = feedRowOf(g); err != nil {
			return nil, 0, err
		}
	}
	bodies, err := readBodies(ctx, q, c.Workspace, taskID, rows, revealed)
	if err != nil {
		return nil, 0, err
	}
	out := []Envelope{}
	for _, r := range rows {
		env, err := rowEnvelope(r, bodies)
		if err != nil {
			return nil, 0, err
		}
		if env != nil {
			out = append(out, *env)
		}
	}
	return out, len(rows), nil
}

// revealedLive is _revealed: a live tool event read back from its row with its bodies revealed.
func (s *Surface) revealedLive(ctx context.Context, c authn.Caller, taskID pgUUID, seq int64) (Envelope, error) {
	sess, release, err := s.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return Envelope{}, err
	}
	defer release()
	row, ok, err := feedAt(ctx, sess, taskID, seq)
	if err != nil {
		return Envelope{}, err
	}
	if !ok {
		return Envelope{}, fmt.Errorf("task %s has no log row %d for its live event", taskID, seq)
	}
	bodies, err := readBodies(ctx, store.New(sess.Q()), c.Workspace, taskID, []feedRow{row}, true)
	if err != nil {
		return Envelope{}, err
	}
	env, err := rowEnvelope(row, bodies)
	if err != nil {
		return Envelope{}, err
	}
	if env == nil {
		return Envelope{}, fmt.Errorf("task %s log row %d is not a feed row", taskID, seq)
	}
	return *env, nil
}
