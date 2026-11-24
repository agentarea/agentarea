package events

import (
	"context"
	"io"
	"log/slog"
	"testing"
	"time"
)

type replayBroker struct {
	Broker
	dead  []Message
	moved []map[string]string
	acked []string
}

func (b *replayBroker) ReadRange(context.Context, string, string, string, int) ([]Message, error) {
	return b.dead, nil
}

func (b *replayBroker) Move(_ context.Context, _, id, _ string, fields map[string]string) (string, error) {
	b.moved = append(b.moved, fields)
	return "new-" + id, nil
}

func (b *replayBroker) Ack(_ context.Context, _, _, id string) error {
	b.acked = append(b.acked, id)
	return nil
}

func quiet() *slog.Logger { return slog.New(slog.NewTextHandler(io.Discard, nil)) }

func TestReplayTargetsTheGroupTheEntryDeadLetteredFrom(t *testing.T) {
	b := &replayBroker{dead: []Message{{ID: "1-0", Fields: map[string]string{
		DeadLetterReasonField: "boom", DeadLetterSourceField: TaskEvents, DeadLetterGroupField: TriggerOutcomeGroup, "id": "e1"}}}}
	res, err := ReplayDeadLetters(context.Background(), b, quiet(), DeadLetterTopic(TaskEvents, TriggerOutcomeGroup), []string{TaskEvents}, "", "", 0)
	if err != nil || res.Moved != 1 {
		t.Fatalf("%+v %v", res, err)
	}
	f := b.moved[0]
	if f[TargetGroupField] != TriggerOutcomeGroup || f[DeadLetterGroupField] != "" || f[DeadLetterReasonField] != "" {
		t.Fatalf("replayed fields %v", f)
	}
}

func TestAGroupAcknowledgesAReplayForAnotherGroupUnprocessed(t *testing.T) {
	b := &replayBroker{}
	bus, err := NewBus(b, quiet(), BusOptions{Retention: time.Hour})
	if err != nil {
		t.Fatal(err)
	}
	fields, err := Encode(IntegrationEvent{ID: "5f0c1c8e-6a52-4c61-9a31-2f4a5a9a7b10", Type: "task.failed", Source: "runs", Time: time.Now().UTC(), Subject: "t"})
	if err != nil {
		t.Fatal(err)
	}
	fields[TargetGroupField] = TriggerOutcomeGroup
	handled := map[string]int{}
	for _, group := range []string{PlatformGroup, TriggerOutcomeGroup} {
		h := func(context.Context, IntegrationEvent) error { handled[group]++; return nil }
		if err := bus.handle(context.Background(), TaskEvents, group, Message{ID: "9-0", Fields: fields, DeliveryCount: 1}, h, nil); err != nil {
			t.Fatal(err)
		}
	}
	if handled[PlatformGroup] != 0 || handled[TriggerOutcomeGroup] != 1 || len(b.acked) != 2 {
		t.Fatalf("handled %v acked %v", handled, b.acked)
	}
}
