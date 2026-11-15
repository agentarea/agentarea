package events

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	kernel "github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

func jsonEqual(t *testing.T, what string, got, want any) {
	t.Helper()
	g, _ := json.Marshal(got)
	w, _ := json.Marshal(want)
	var gv, wv any
	_ = json.Unmarshal(g, &gv)
	_ = json.Unmarshal(w, &wv)
	gb, _ := json.Marshal(gv)
	wb, _ := json.Marshal(wv)
	if string(gb) != string(wb) {
		t.Errorf("%s\n got %s\nwant %s", what, gb, wb)
	}
}

func workspace(t *testing.T) scope.Workspace {
	w, err := scope.NewWorkspace("ws-"+uuid.NewString()[:8], "")
	if err != nil {
		t.Fatal(err)
	}
	return w
}

type outboxRow struct {
	EventID, EventType, AggregateID, AggregateType, WorkspaceID, CreatedBy string
	Payload                                                                json.RawMessage
	Published                                                              bool
}

func outboxRows(t *testing.T, d *db.Pools) []outboxRow {
	t.Helper()
	ctx := context.Background()
	q, release, err := d.Global().Read(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	rs, err := q.Query(ctx, `SELECT event_id::text, event_type, aggregate_id, aggregate_type, workspace_id, created_by,
		payload::text, published_at IS NOT NULL FROM event_outbox ORDER BY created_at`)
	if err != nil {
		t.Fatal(err)
	}
	defer rs.Close()
	var out []outboxRow
	for rs.Next() {
		var r outboxRow
		var payload string
		if err := rs.Scan(&r.EventID, &r.EventType, &r.AggregateID, &r.AggregateType, &r.WorkspaceID, &r.CreatedBy, &payload, &r.Published); err != nil {
			t.Fatal(err)
		}
		r.Payload = json.RawMessage(payload)
		out = append(out, r)
	}
	if err := rs.Err(); err != nil {
		t.Fatal(err)
	}
	return out
}

func newRelay(t *testing.T, d *db.Pools, b *Broker) *kernel.Relay {
	t.Helper()
	bus, err := kernel.NewBus(b, slog.Default(), kernel.BusOptions{Retention: kernel.BusRetention})
	if err != nil {
		t.Fatal(err)
	}
	return kernel.NewRelay(d, bus, slog.Default(), kernel.RelayOptions{})
}

// Publish writes the row on the caller's transaction (none when it rolls
// back); the relay puts it on domain.events.<type> once and marks it.
func TestOutboxWritesAndRelays(t *testing.T) {
	e := testEnv(t)
	d := freshDatabase(t, e)
	ns := namespace()
	b := newBroker(t, e, ns)
	ctx := context.Background()
	ws := workspace(t)

	env := kernel.Envelope{
		EventID: uuid.NewString(), Timestamp: time.Date(2026, 11, 12, 9, 30, 0, 250000000, time.UTC),
		EventType: "TaskStatusChanged",
		Data:      map[string]any{"task_id": "task-1", "old_status": "pending", "new_status": "running", "note": "é"},
	}
	if err := d.Write(ctx, ws, func(ctx context.Context, s db.Session) error {
		return kernel.Publish(ctx, s, "user-go", env)
	}); err != nil {
		t.Fatal(err)
	}
	rolledBack := kernel.NewEnvelope("TaskStatusChanged", map[string]any{"task_id": "task-2"})
	_ = d.Write(ctx, ws, func(ctx context.Context, s db.Session) error {
		if err := kernel.Publish(ctx, s, "user-go", rolledBack); err != nil {
			return err
		}
		return errors.New("the change failed")
	})

	rows := outboxRows(t, d)
	if len(rows) != 1 {
		t.Fatalf("%d rows, want 1 (the rolled back one must not exist): %+v", len(rows), rows)
	}
	r := rows[0]
	if r.EventID != env.EventID || r.EventType != "TaskStatusChanged" || r.AggregateID != "task-1" || r.AggregateType != "task" ||
		r.WorkspaceID != ws.ID() || r.CreatedBy != "user-go" || r.Published {
		t.Errorf("row %+v", r)
	}
	want := `{"data":{"new_status":"running","note":"é","old_status":"pending","task_id":"task-1"},"event_id":"` + env.EventID +
		`","event_type":"TaskStatusChanged","timestamp":"2026-11-12T09:30:00.250000+00:00"}`
	if got := string(must(canonical(r.Payload))); got != want {
		t.Errorf("payload\n got %s\nwant %s", got, want)
	}

	relay := newRelay(t, d, b)
	if n, err := relay.ProcessBatch(ctx); err != nil || n != 1 {
		t.Fatalf("relay published %d, %v", n, err)
	}
	if n, err := relay.ProcessBatch(ctx); err != nil || n != 0 {
		t.Fatalf("second pass published %d, %v", n, err)
	}
	msgs, err := b.ReadRange(ctx, kernel.DomainEventsTopic("TaskStatusChanged"), "-", "+", 10)
	if err != nil || len(msgs) != 1 {
		t.Fatalf("stream: %v %v", msgs, err)
	}
	got, err := kernel.Decode(msgs[0].Fields)
	if err != nil {
		t.Fatal(err)
	}
	if got.ID != env.EventID || got.Source != "agentarea-outbox" || got.Subject != "" || !got.Time.Equal(env.Timestamp) {
		t.Errorf("relayed event %+v", got)
	}
	if msgs[0].Fields["ce_time"] != "2026-11-12T09:30:00.250000+00:00" {
		t.Errorf("ce_time = %s", msgs[0].Fields["ce_time"])
	}
	jsonEqual(t, "relayed data", got.Data, env.Data)
	if rows := outboxRows(t, d); len(rows) != 1 || !rows[0].Published {
		t.Errorf("row not marked published: %+v", rows)
	}
}

type storedOutboxRow struct {
	ID            string          `json:"id"`
	CreatedAt     string          `json:"created_at"`
	WorkspaceID   string          `json:"workspace_id"`
	CreatedBy     string          `json:"created_by"`
	EventID       string          `json:"event_id"`
	EventType     string          `json:"event_type"`
	AggregateID   string          `json:"aggregate_id"`
	AggregateType string          `json:"aggregate_type"`
	Payload       json.RawMessage `json:"payload"`
	Attempts      int             `json:"attempts"`
	LastError     *string         `json:"last_error"`
	NextAttemptAt *string         `json:"next_attempt_at"`
}

// Rows the Python backend left unpublished at cutover
// (testdata/stored_outbox_rows.json): the relay publishes them with the
// stream fields their readers know, and the envelope derives the aggregate
// the row names.
func TestOutboxRelaysStoredRows(t *testing.T) {
	e := testEnv(t)
	d := freshDatabase(t, e)
	ns := namespace()
	b := newBroker(t, e, ns)
	ctx := context.Background()

	raw, err := os.ReadFile(filepath.Join("testdata", "stored_outbox_rows.json"))
	if err != nil {
		t.Fatal(err)
	}
	var stored []storedOutboxRow
	if err := json.Unmarshal(raw, &stored); err != nil {
		t.Fatal(err)
	}
	if err := d.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		for _, r := range stored {
			if _, err := q.Exec(ctx, `INSERT INTO event_outbox
				(id, created_at, updated_at, workspace_id, created_by, event_id, event_type, aggregate_id,
				 aggregate_type, payload, attempts, last_error, next_attempt_at)
				VALUES ($1, $2::timestamp, $2::timestamp, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11, $12::timestamp)`,
				r.ID, r.CreatedAt, r.WorkspaceID, r.CreatedBy, r.EventID, r.EventType, r.AggregateID,
				r.AggregateType, string(r.Payload), r.Attempts, r.LastError, r.NextAttemptAt); err != nil {
				return err
			}
		}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	for _, r := range stored {
		env, err := kernel.ParseEnvelope(r.Payload)
		if err != nil {
			t.Fatal(err)
		}
		if env.AggregateID() != r.AggregateID || env.AggregateType() != r.AggregateType {
			t.Errorf("%s: derived %s/%s, stored %s/%s", r.EventType, env.AggregateID(), env.AggregateType(), r.AggregateID, r.AggregateType)
		}
	}

	if n, err := newRelay(t, d, b).ProcessBatch(ctx); err != nil || n != 2 {
		t.Fatalf("relay published %d, %v", n, err)
	}
	for _, r := range outboxRows(t, d) {
		if !r.Published {
			t.Errorf("stored row %s not published", r.EventID)
		}
	}

	msgs, err := b.ReadRange(ctx, kernel.DomainEventsTopic("AgentUpdated"), "-", "+", 10)
	if err != nil || len(msgs) != 1 {
		t.Fatalf("stream: %v %v", msgs, err)
	}
	f := msgs[0].Fields
	if f["ce_id"] != stored[0].EventID || f["ce_source"] != "agentarea-outbox" || f["ce_subject"] != "agent-1" ||
		f["ce_time"] != "2026-11-12T09:30:00.250000+00:00" {
		t.Errorf("fields %v", f)
	}
	if f["data"] != `{"agent_id": "agent-1", "aggregate_id": "agent-1", "event_type": "AgentUpdated", "name": "`+`\u00e9 \u00fcn\u00ef"}` {
		t.Errorf("data field %s", f["data"])
	}
	msgs, err = b.ReadRange(ctx, kernel.DomainEventsTopic("TaskStatusChanged"), "-", "+", 10)
	if err != nil || len(msgs) != 1 {
		t.Fatalf("stream: %v %v", msgs, err)
	}
	if f := msgs[0].Fields; f["ce_id"] != stored[1].EventID || f["ce_time"] != "2026-11-12T09:31:00+00:00" {
		t.Errorf("retried row fields %v", f)
	}
}

// A handler row is performed in its workspace on the relay transaction and,
// failing, retried later without counting against the publish budget.
func TestRelayHandlerRetries(t *testing.T) {
	e := testEnv(t)
	d := freshDatabase(t, e)
	ctx := context.Background()
	ws := workspace(t)
	if err := d.Write(ctx, ws, func(ctx context.Context, s db.Session) error {
		return kernel.Publish(ctx, s, "u", kernel.NewEnvelope("MembershipEnded", map[string]any{"member": "m"}))
	}); err != nil {
		t.Fatal(err)
	}
	fail := true
	var seen []string
	now := time.Now().UTC()
	relay := kernel.NewRelay(d, nil, slog.Default(), kernel.RelayOptions{
		Now: func() time.Time { return now },
		Handlers: map[string]kernel.OutboxHandler{"MembershipEnded": func(ctx context.Context, s db.Session, env kernel.Envelope) error {
			seen = append(seen, s.Workspace().ID())
			if _, err := s.Q().Exec(ctx, "CREATE TEMP TABLE handler_side_effect (n int)"); err != nil {
				return err
			}
			if fail {
				return errors.New("graph down")
			}
			return nil
		}},
	})
	if n, err := relay.ProcessBatch(ctx); err != nil || n != 0 {
		t.Fatalf("first pass %d %v", n, err)
	}
	if n, _ := relay.ProcessBatch(ctx); n != 0 || len(seen) != 1 {
		t.Fatalf("retried before its backoff: %d %v", n, seen)
	}
	now = now.Add(2 * time.Second)
	fail = false
	if n, err := relay.ProcessBatch(ctx); err != nil || n != 1 {
		t.Fatalf("retry pass %d %v", n, err)
	}
	if !slices.Equal(seen, []string{ws.ID(), ws.ID()}) {
		t.Errorf("handler ran in %v", seen)
	}
}

// A task event goes on tasks.events with the fields the feeds decode.
func TestTaskEventsStream(t *testing.T) {
	e := testEnv(t)
	ns := namespace()
	b := newBroker(t, e, ns)
	ctx := context.Background()
	bus, err := kernel.NewBus(b, slog.Default(), kernel.BusOptions{Retention: kernel.BusRetention})
	if err != nil {
		t.Fatal(err)
	}
	ev := kernel.IntegrationEvent{
		ID: uuid.NewString(), Type: "task.completed", Source: "agentarea-worker", Subject: "task-1",
		Time:       time.Date(2026, 11, 12, 10, 0, 0, 123456000, time.UTC),
		Data:       map[string]any{"result": "ok é", "n": 3, "nested": map[string]any{"a": []any{1, nil}}},
		Extensions: map[string]string{"workspace": "ws-1", "seq": "43"},
	}
	if err := bus.Publish(ctx, ev, kernel.TaskEvents); err != nil {
		t.Fatal(err)
	}
	msgs, err := b.ReadRange(ctx, kernel.TaskEvents, "-", "+", 10)
	if err != nil || len(msgs) != 1 {
		t.Fatalf("%v %v", msgs, err)
	}
	f := msgs[0].Fields
	want := []string{"ce_datacontenttype", "ce_id", "ce_seq", "ce_source", "ce_specversion", "ce_subject", "ce_time", "ce_type", "ce_workspace", "data"}
	if got := slices.Sorted(maps.Keys(f)); !slices.Equal(got, want) {
		t.Errorf("fields %v, want %v", got, want)
	}
	if f["ce_time"] != "2026-11-12T10:00:00.123456+00:00" || f["data"] != `{"n": 3, "nested": {"a": [1, null]}, "result": "ok `+`\u00e9"}` {
		t.Errorf("fields %v", f)
	}
	got, err := kernel.Decode(f)
	if err != nil {
		t.Fatal(err)
	}
	if got.ID != ev.ID || got.Extensions["seq"] != "43" || got.Subject != "task-1" || !got.Time.Equal(ev.Time) {
		t.Errorf("decoded %+v", got)
	}
	jsonEqual(t, "data", got.Data, ev.Data)
}

// Live-only signals and events-page notices go over pub/sub: nothing kept.
func TestLiveChannels(t *testing.T) {
	e := testEnv(t)
	ns := namespace()
	b := newBroker(t, e, ns)
	ctx := context.Background()

	live, err := b.OpenLive(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = live.Close() }()
	if err := live.Subscribe(ctx, kernel.TaskLiveChannel("task-9")); err != nil {
		t.Fatal(err)
	}
	if err := live.Subscribe(ctx, kernel.StreamsLiveChannel("ws-9")); err != nil {
		t.Fatal(err)
	}
	if _, _, ok, err := live.Next(ctx, 200*time.Millisecond); ok || err != nil {
		t.Fatalf("idle Next = %v %v", ok, err)
	}
	id := uuid.NewString()
	fields, err := kernel.Encode(kernel.IntegrationEvent{ID: id, Type: "llm.call.chunk", Source: "agentarea-worker", Subject: "task-9",
		Time: time.Date(2026, 11, 12, 10, 0, 1, 0, time.UTC), Data: map[string]any{"chunk": "Hel"}})
	if err != nil {
		t.Fatal(err)
	}
	if err := b.Notify(ctx, kernel.TaskLiveChannel("task-9"), fields); err != nil {
		t.Fatal(err)
	}
	if err := b.Notify(ctx, kernel.StreamsLiveChannel("ws-9"), map[string]string{"type": "event.recorded", "event_id": id, "stream_id": "task-9"}); err != nil {
		t.Fatal(err)
	}
	if err := b.Notify(ctx, kernel.TaskLiveChannel("task-other"), fields); err != nil {
		t.Fatal(err)
	}
	got := map[string]map[string]string{}
	for len(got) < 2 {
		ch, f, ok, err := live.Next(ctx, 5*time.Second)
		if err != nil || !ok {
			t.Fatalf("Next = %v %v (got %v)", ok, err, got)
		}
		got[ch] = f
	}
	chunk, err := kernel.Decode(got["tasks.live.task-9"])
	if err != nil || chunk.ID != id || chunk.Type != "llm.call.chunk" || chunk.Data["chunk"] != "Hel" || chunk.Subject != "task-9" {
		t.Errorf("live signal %+v %v", chunk, err)
	}
	if got["tasks.live.task-9"]["ce_time"] != "2026-11-12T10:00:01+00:00" {
		t.Errorf("ce_time %s", got["tasks.live.task-9"]["ce_time"])
	}
	if n := got["streams.live.ws-9"]; n["type"] != "event.recorded" || n["event_id"] != id || n["stream_id"] != "task-9" {
		t.Errorf("notice %v", n)
	}
	if ch, _, ok, err := live.Next(ctx, 200*time.Millisecond); ok || err != nil {
		t.Errorf("heard %s on a channel not subscribed (%v)", ch, err)
	}
}

// Consumer groups: a group over partitions reads what is published and
// dead-letters what fails; replay moves dead letters back once.
func TestConsumerGroups(t *testing.T) {
	e := testEnv(t)
	ns := namespace()
	b := newBroker(t, e, ns)
	ctx := context.Background()
	bus, err := kernel.NewBus(b, slog.Default(), kernel.BusOptions{
		Retention: kernel.BusRetention, MaxDelivery: 2, MinIdle: 150 * time.Millisecond, Block: 100 * time.Millisecond,
	})
	if err != nil {
		t.Fatal(err)
	}
	partitions := kernel.StreamEventsPartitions(2)
	dlq := kernel.DeadLetterTopic(kernel.StreamEvents, kernel.RouterGroup)

	var mu sync.Mutex
	handled := map[string]int{}
	var deadLettered []string
	received := make(chan kernel.IntegrationEvent, 10)
	sub, err := bus.SubscribeMany(ctx, partitions, kernel.RouterGroup, func(ctx context.Context, ev kernel.IntegrationEvent) error {
		mu.Lock()
		handled[ev.ID]++
		mu.Unlock()
		switch ev.Data["mode"] {
		case "poison":
			return errors.New("always fails")
		case "unprocessable":
			return fmt.Errorf("%w: no such stream", kernel.ErrUnprocessable)
		}
		received <- ev
		return nil
	}, dlq, func(ctx context.Context, ev kernel.IntegrationEvent) error {
		mu.Lock()
		deadLettered = append(deadLettered, ev.ID)
		mu.Unlock()
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = sub.Stop(ctx) }()

	firstID := uuid.NewString()
	if err := bus.Publish(ctx, kernel.IntegrationEvent{ID: firstID, Type: "webhook.received", Source: "agentarea-api", Subject: "stream-1",
		Time: time.Date(2026, 11, 12, 11, 0, 0, 0, time.UTC), CorrelationID: "corr-1",
		Data: map[string]any{"body": map[string]any{"k": "v"}}, Extensions: map[string]string{"streamid": "stream-1", "depth": "0"}}, partitions[1]); err != nil {
		t.Fatal(err)
	}
	select {
	case ev := <-received:
		if ev.ID != firstID || ev.Type != "webhook.received" || ev.CorrelationID != "corr-1" || ev.Extensions["streamid"] != "stream-1" {
			t.Errorf("group got %+v", ev)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("group did not receive the event")
	}

	poison := kernel.IntegrationEvent{ID: uuid.NewString(), Type: "x", Source: "go", Data: map[string]any{"mode": "poison"}}
	unproc := kernel.IntegrationEvent{ID: uuid.NewString(), Type: "x", Source: "go", Data: map[string]any{"mode": "unprocessable"}}
	for _, ev := range []kernel.IntegrationEvent{poison, unproc} {
		if err := bus.Publish(ctx, ev, partitions[0]); err != nil {
			t.Fatal(err)
		}
	}
	deadline := time.Now().Add(15 * time.Second)
	for {
		n, err := b.Length(ctx, dlq)
		if err != nil {
			t.Fatal(err)
		}
		if n == 2 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("dead letters %d, handled %v", n, handled)
		}
		time.Sleep(50 * time.Millisecond)
	}
	letters, err := b.ReadRange(ctx, dlq, "-", "+", 10)
	if err != nil {
		t.Fatal(err)
	}
	reasons := map[string]string{}
	for _, m := range letters {
		if m.Fields[kernel.DeadLetterSourceField] != partitions[0] {
			t.Errorf("dead letter source %q", m.Fields[kernel.DeadLetterSourceField])
		}
		reasons[m.Fields["ce_id"]] = m.Fields[kernel.DeadLetterReasonField]
	}
	if reasons[unproc.ID] != "unprocessable: unprocessable event: no such stream" {
		t.Errorf("unprocessable reason %q", reasons[unproc.ID])
	}
	if reasons[poison.ID] != "max delivery attempts (2) exceeded" {
		t.Errorf("poison reason %q", reasons[poison.ID])
	}
	mu.Lock()
	if handled[poison.ID] != 2 || handled[unproc.ID] != 1 || !slices.Equal(deadLettered, []string{poison.ID}) {
		t.Errorf("handled %v, dead-lettered %v", handled, deadLettered)
	}
	mu.Unlock()
	if p, err := b.Pending(ctx, partitions[0], kernel.RouterGroup); err != nil || p.Count != 0 {
		t.Errorf("pending after dead-lettering %+v %v", p, err)
	}

	// A running group dead-letters a replayed message again under a new id,
	// which a later replay rightly moves (broker/dlq.py does the same); stop
	// it so the second replay shows that one dead letter is moved once.
	if err := sub.Stop(ctx); err != nil {
		t.Fatal(err)
	}
	before, err := b.Length(ctx, partitions[0])
	if err != nil {
		t.Fatal(err)
	}
	res, err := kernel.ReplayDeadLetters(ctx, b, slog.Default(), dlq, partitions, "", "", 0)
	if err != nil || res.Moved != 2 {
		t.Fatalf("replay %+v %v", res, err)
	}
	if res, err := kernel.ReplayDeadLetters(ctx, b, slog.Default(), dlq, partitions, "", "", 0); err != nil || res.Moved != 0 {
		t.Errorf("second replay moved %d, %v", res.Moved, err)
	}
	if after, _ := b.Length(ctx, partitions[0]); after != before+2 {
		t.Errorf("source holds %d after replay, want %d", after, before+2)
	}
	if n, _ := b.Length(ctx, dlq); n != 0 {
		t.Errorf("dead-letter topic holds %d after replay", n)
	}

	goID := uuid.NewString()
	topic := "streams.ingest"
	if err := bus.Publish(ctx, kernel.IntegrationEvent{ID: goID, Type: "item", Source: "go", Subject: "src-1", Data: map[string]any{"k": "v"}}, topic); err != nil {
		t.Fatal(err)
	}
	if err := b.EnsureGroup(ctx, topic, "ingest", "0"); err != nil {
		t.Fatal(err)
	}
	consumed, err := b.Consume(ctx, topic, "ingest", "c1", 10, time.Second)
	if err != nil || len(consumed) != 1 || consumed[0].DeliveryCount != 1 || consumed[0].Fields["ce_id"] != goID {
		t.Fatalf("group consumed %+v %v", consumed, err)
	}
	if err := b.Ack(ctx, topic, "ingest", consumed[0].ID); err != nil {
		t.Fatal(err)
	}
	info, err := b.GroupInfo(ctx, topic, "ingest")
	if err != nil || info == nil || info.Lag != 0 || info.Consumers != 1 || info.LastDeliveredID != consumed[0].ID {
		t.Fatalf("GroupInfo %+v %v", info, err)
	}
	if p, err := b.Pending(ctx, topic, "ingest"); err != nil || p.Count != 0 {
		t.Errorf("pending after ack %+v %v", p, err)
	}
	if missing, err := b.GroupInfo(ctx, "no.such.stream", "g"); err != nil || missing != nil {
		t.Errorf("missing stream: %v %v", missing, err)
	}
}

// The broker's group lifecycle: lost groups recreated, reclaim from dead
// consumers, Move once.
func TestBrokerGroupLifecycle(t *testing.T) {
	e := testEnv(t)
	ns := namespace()
	b := newBroker(t, e, ns)
	ctx := context.Background()
	if err := b.EnsureGroup(ctx, "s", "g", "$"); err != nil {
		t.Fatal(err)
	}
	if err := b.EnsureGroup(ctx, "s", "g", "$"); err != nil {
		t.Fatalf("EnsureGroup is not idempotent: %v", err)
	}
	id, err := b.Submit(ctx, "s", map[string]string{"a": "1"}, time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	if last, _ := b.LastID(ctx, "s"); last != id {
		t.Errorf("LastID %s, want %s", last, id)
	}
	if last, _ := b.LastID(ctx, "empty"); last != "0-0" {
		t.Errorf("LastID of nothing %s", last)
	}
	msgs, err := b.Consume(ctx, "s", "g", "dead", 10, 100*time.Millisecond)
	if err != nil || len(msgs) != 1 || msgs[0].DeliveryCount != 1 || msgs[0].Stream != "s" {
		t.Fatalf("Consume %+v %v", msgs, err)
	}
	time.Sleep(60 * time.Millisecond)
	claimed, err := b.Autoclaim(ctx, "s", "g", "alive", 50*time.Millisecond, "", 10)
	if err != nil || len(claimed) != 1 || claimed[0].DeliveryCount != 2 {
		t.Fatalf("Autoclaim %+v %v", claimed, err)
	}
	if p, err := b.Pending(ctx, "s", "g"); err != nil || p.Count != 1 || p.OldestAge == nil {
		t.Errorf("Pending %+v %v", p, err)
	}
	if err := b.Ack(ctx, "s", "g", id); err != nil {
		t.Fatal(err)
	}

	if err := b.client.Del(ctx, ns+".s").Err(); err != nil {
		t.Fatal(err)
	}
	if _, err := b.Submit(ctx, "s", map[string]string{"a": "2"}, time.Hour); err != nil {
		t.Fatal(err)
	}
	msgs, err = b.Consume(ctx, "s", "g", "c", 10, 100*time.Millisecond)
	if err != nil || len(msgs) != 1 || msgs[0].Fields["a"] != "2" {
		t.Errorf("after the group was lost: %+v %v", msgs, err)
	}

	moved, err := b.Move(ctx, "s", msgs[0].ID, "t", map[string]string{"b": "3"})
	if err != nil || moved == "" {
		t.Fatalf("Move %q %v", moved, err)
	}
	if again, err := b.Move(ctx, "s", msgs[0].ID, "t", map[string]string{"b": "3"}); err != nil || again != "" {
		t.Errorf("second Move %q %v", again, err)
	}
	if n, _ := b.Length(ctx, "t"); n != 1 {
		t.Errorf("target holds %d", n)
	}

	next, got, err := b.Tail(ctx, "t", "0", 100*time.Millisecond, 10)
	if err != nil || len(got) != 1 || next != moved {
		t.Errorf("Tail %s %+v %v", next, got, err)
	}
	if same, got, err := b.Tail(ctx, "t", next, 50*time.Millisecond, 10); err != nil || len(got) != 0 || same != next {
		t.Errorf("idle Tail %s %+v %v", same, got, err)
	}

	r := kernel.NewStreamReader(b, slog.Default(), 100*time.Millisecond)
	rctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	bus, _ := kernel.NewBus(b, slog.Default(), kernel.BusOptions{Retention: time.Hour})
	for i := range 2 {
		if err := bus.Publish(ctx, kernel.IntegrationEvent{Type: "n", Source: "go", Data: map[string]any{"i": i}}, "read"); err != nil {
			t.Fatal(err)
		}
	}
	n := 0
	for ev, err := range r.Read(rctx, "read", "0") {
		if err != nil {
			t.Fatal(err)
		}
		if fmt.Sprint(ev.Data["i"]) != fmt.Sprint(n) {
			t.Errorf("read out of order: %v", ev.Data)
		}
		if n++; n == 2 {
			break
		}
	}
}

// Claims live under <namespace>.dedup.<prefix>:<key>; a claim left before
// cutover ("1" with the dedup TTL) still counts.
func TestDedup(t *testing.T) {
	e := testEnv(t)
	ns := namespace()
	b := newBroker(t, e, ns)
	ctx := context.Background()
	d, err := NewDedup(b.client, ns, "channel-delivery", time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	key := func(k string) string { return ns + ".dedup.channel-delivery:" + k }
	if err := b.client.Set(ctx, key("telegram:1:1"), "1", time.Hour).Err(); err != nil {
		t.Fatal(err)
	}
	if ok, err := d.Contains(ctx, "telegram:1:1"); err != nil || !ok {
		t.Errorf("stored claim not seen: %v %v", ok, err)
	}
	if ok, err := d.Claim(ctx, "telegram:1:1", 0); err != nil || ok {
		t.Errorf("stored claim claimed again: %v %v", ok, err)
	}
	if ok, err := d.Claim(ctx, "telegram:1:2", time.Minute); err != nil || !ok {
		t.Fatalf("claim %v %v", ok, err)
	}
	if ttl := b.client.TTL(ctx, key("telegram:1:2")).Val(); ttl <= 0 || ttl > time.Minute {
		t.Errorf("held claim ttl %s", ttl)
	}
	if ok, err := d.Claim(ctx, "telegram:1:2", time.Minute); err != nil || ok {
		t.Errorf("held claim claimed again: %v %v", ok, err)
	}
	if err := d.Keep(ctx, "telegram:1:2"); err != nil {
		t.Fatal(err)
	}
	if ttl := b.client.TTL(ctx, key("telegram:1:2")).Val(); ttl <= time.Minute {
		t.Errorf("kept claim ttl %s", ttl)
	}
	if v := b.client.Get(ctx, key("telegram:1:2")).Val(); v != "1" {
		t.Errorf("claim value %q", v)
	}
	if err := d.Release(ctx, "telegram:1:1"); err != nil {
		t.Fatal(err)
	}
	if ok, _ := d.Contains(ctx, "telegram:1:1"); ok {
		t.Error("released claim still seen")
	}
	if ok, err := d.Claim(ctx, "telegram:1:1", 0); err != nil || !ok {
		t.Errorf("released key not claimable: %v %v", ok, err)
	}
}

func canonical(raw []byte) ([]byte, error) {
	var v any
	if err := json.Unmarshal(raw, &v); err != nil {
		return nil, err
	}
	return json.Marshal(v)
}

func must(b []byte, err error) []byte {
	if err != nil {
		panic(err)
	}
	return b
}
