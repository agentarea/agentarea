package ingest

import (
	"context"
	"encoding/json"
	"errors"
	"testing"
	"time"
)

type recorded struct {
	stream    string
	fields    map[string]string
	retention time.Duration
}

type fakeBroker struct {
	got []recorded
	err error
}

func (f *fakeBroker) Submit(_ context.Context, stream string, fields map[string]string, retention time.Duration) (string, error) {
	if f.err != nil {
		return "", f.err
	}
	f.got = append(f.got, recorded{stream, fields, retention})
	return "1-0", nil
}

func TestItemPublishesTheRawItem(t *testing.T) {
	b := &fakeBroker{}
	p := NewPublisher(b)
	p.now = func() time.Time { return time.Date(2026, 10, 15, 10, 0, 0, 5, time.UTC) }

	if err := p.Item(context.Background(), "src-1", map[string]any{"update_id": json.Number("9007199254740993")}); err != nil {
		t.Fatalf("Item: %v", err)
	}
	if len(b.got) != 1 {
		t.Fatalf("published %d", len(b.got))
	}
	m := b.got[0]
	if m.stream != "streams.ingest" || m.retention != 72*time.Hour {
		t.Fatalf("message = %+v", m)
	}
	if m.fields["source_id"] != "src-1" || m.fields["kind"] != "item" ||
		m.fields["item"] != `{"update_id":9007199254740993}` || m.fields["received_at"] != "2026-10-15T10:00:00.000000005Z" {
		t.Fatalf("fields = %v", m.fields)
	}
}

func TestGapPublishesTheReason(t *testing.T) {
	b := &fakeBroker{}
	if err := NewPublisher(b).Gap(context.Background(), "src-1", "renumbered"); err != nil {
		t.Fatalf("Gap: %v", err)
	}
	if b.got[0].fields["kind"] != "gap" || b.got[0].fields["item"] != `{"reason":"renumbered"}` {
		t.Fatalf("fields = %v", b.got[0].fields)
	}
}

func TestABrokerFailureIsReturned(t *testing.T) {
	b := &fakeBroker{err: errors.New("down")}
	if err := NewPublisher(b).Item(context.Background(), "src-1", 1); err == nil {
		t.Fatal("a failed publish reported success")
	}
}
