package polling

import (
	"context"
	"log/slog"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
)

// What the event service published to streams.ingest is ingested after the cutover.
func TestTheEventServiceBacklogIsIngested(t *testing.T) {
	broker := newFakeBroker()
	ctx := context.Background()
	pub := &fakePublisher{}
	b := Backlog{Broker: broker, Intake: pub, Consumer: "c1", Block: time.Millisecond, Batch: 10, Log: slog.Default()}
	if err := broker.EnsureGroup(ctx, events.StreamsIngest, events.IngestGroup, "0"); err != nil {
		t.Fatal(err)
	}
	at := "2026-11-12T10:00:00.5Z"
	for _, f := range []map[string]string{
		{"source_id": "s1", "kind": "item", "item": `{"update_id":9007199254740993}`, "received_at": at},
		{"source_id": "s1", "kind": "gap", "item": `{"reason":"renumbered"}`, "received_at": at},
		{"source_id": "s1", "kind": "item", "item": `{not json`, "received_at": at},
	} {
		if _, err := broker.Submit(ctx, events.StreamsIngest, f, events.BusRetention); err != nil {
			t.Fatal(err)
		}
	}
	if err := b.round(ctx); err != nil {
		t.Fatal(err)
	}
	if len(pub.got) != 2 || pub.got[1].gap != "renumbered" {
		t.Fatalf("ingested = %+v", pub.got)
	}
	if n, _ := pub.got[0].item.(map[string]any)["update_id"].(float64); n == 0 {
		t.Fatalf("item = %+v", pub.got[0].item)
	}
	dead, err := broker.ReadRange(ctx, events.DeadLetterTopic(events.StreamsIngest, events.IngestGroup), "-", "+", 10)
	if err != nil || len(dead) != 1 {
		t.Fatalf("dead = %d, %v", len(dead), err)
	}
	pending, err := broker.Pending(ctx, events.StreamsIngest, events.IngestGroup)
	if err != nil || pending.Count != 0 {
		t.Fatalf("pending = %+v, %v", pending, err)
	}
}
