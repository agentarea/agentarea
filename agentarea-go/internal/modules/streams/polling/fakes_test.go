package polling

import (
	"context"
	"strconv"
	"sync"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
)

// fakeBroker is the broker calls the backlog makes: topics, one group each, pending until acked.
type fakeBroker struct {
	events.Broker
	mu      sync.Mutex
	seq     int
	topics  map[string][]events.Message
	next    map[string]int
	pending map[string]map[string]bool
}

func newFakeBroker() *fakeBroker {
	return &fakeBroker{topics: map[string][]events.Message{}, next: map[string]int{}, pending: map[string]map[string]bool{}}
}

func (b *fakeBroker) Submit(_ context.Context, topic string, fields map[string]string, _ time.Duration) (string, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.seq++
	id := strconv.Itoa(b.seq) + "-0"
	b.topics[topic] = append(b.topics[topic], events.Message{ID: id, Fields: fields, Stream: topic})
	return id, nil
}

func (b *fakeBroker) EnsureGroup(context.Context, string, string, string) error { return nil }

func (b *fakeBroker) Consume(_ context.Context, topic, _, _ string, count int, _ time.Duration) ([]events.Message, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	var out []events.Message
	for b.next[topic] < len(b.topics[topic]) && len(out) < count {
		m := b.topics[topic][b.next[topic]]
		b.next[topic]++
		if b.pending[topic] == nil {
			b.pending[topic] = map[string]bool{}
		}
		b.pending[topic][m.ID] = true
		out = append(out, m)
	}
	return out, nil
}

func (b *fakeBroker) Autoclaim(context.Context, string, string, string, time.Duration, string, int) ([]events.Message, error) {
	return nil, nil
}

func (b *fakeBroker) Ack(_ context.Context, topic, _, id string) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	delete(b.pending[topic], id)
	return nil
}

func (b *fakeBroker) Pending(_ context.Context, topic, _ string) (events.PendingSummary, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return events.PendingSummary{Count: int64(len(b.pending[topic]))}, nil
}

func (b *fakeBroker) ReadRange(_ context.Context, topic, _, _ string, count int) ([]events.Message, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	msgs := b.topics[topic]
	return msgs[:min(count, len(msgs))], nil
}
