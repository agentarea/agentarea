package service

import (
	"context"
	"log/slog"
	"maps"
	"slices"
	"strings"
	"sync"
	"time"
)

// Analytics sender limits (analytics/sender.py).
const (
	MaxBatch         = 500
	MaxCounterSeries = 1000
	MaxQueued        = 10_000
	FlushEvery       = time.Hour
	failureLogEvery  = 24 * time.Hour
)

// Collector posts one batch of events; an error drops the batch.
type Collector interface {
	Post(ctx context.Context, batch []map[string]any) error
}

type counterKey struct {
	name   string
	labels string
}

// Sender is AnalyticsSender: events held in memory and posted to the collector in batches.
// Nothing here fails a caller; a batch the collector does not take is logged and dropped.
type Sender struct {
	collector Collector
	context   map[string]any
	now       func() time.Time
	log       *slog.Logger

	mu       sync.Mutex
	queue    []map[string]any
	counts   map[counterKey]int
	labelsOf map[counterKey]map[string]string
	order    []counterKey

	failureLoggedAt *time.Time
	droppedUnlogged int
	droppedInOutage int
}

// NewSender is a sender reporting as installID.
func NewSender(installID, version, edition string, c Collector, now func() time.Time, log *slog.Logger) *Sender {
	if now == nil {
		now = time.Now
	}
	return &Sender{collector: c, now: now, log: log,
		context: map[string]any{"install_id": installID, "version": version, "edition": edition},
		counts:  map[counterKey]int{}, labelsOf: map[counterKey]map[string]string{}}
}

// Enqueue queues event (event, properties, user_id and the like); the oldest is dropped past MaxQueued.
func (s *Sender) Enqueue(event map[string]any) {
	e := map[string]any{"occurred_at": s.now().UTC().Format("2006-01-02T15:04:05.000000+00:00"), "properties": map[string]any{}}
	maps.Copy(e, event)
	e["context"] = s.context
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.queue) >= MaxQueued {
		s.queue = s.queue[len(s.queue)-MaxQueued+1:]
	}
	s.queue = append(s.queue, e)
}

// Count adds one to the counter name under labels; past MaxCounterSeries distinct series a new
// one is folded into its name under {"overflow": "true"}.
func (s *Sender) Count(name string, labels map[string]string) {
	keys := slices.Sorted(maps.Keys(labels))
	var b strings.Builder
	for _, k := range keys {
		b.WriteString(k + "\x00" + labels[k] + "\x00")
	}
	key := counterKey{name, b.String()}
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, seen := s.counts[key]; !seen && len(s.counts) >= MaxCounterSeries {
		key, labels = counterKey{name, "overflow\x00true\x00"}, map[string]string{"overflow": "true"}
	}
	if _, seen := s.counts[key]; !seen {
		s.order = append(s.order, key)
		s.labelsOf[key] = maps.Clone(labels)
	}
	s.counts[key]++
}

// RollUp queues the counts since the last roll-up as one counters event and resets them.
func (s *Sender) RollUp() {
	s.mu.Lock()
	order, counts, labels := s.order, s.counts, s.labelsOf
	s.order, s.counts, s.labelsOf = nil, map[counterKey]int{}, map[counterKey]map[string]string{}
	s.mu.Unlock()
	if len(order) == 0 {
		return
	}
	out := make([]map[string]any, 0, len(order))
	for _, k := range order {
		l := labels[k]
		if l == nil {
			l = map[string]string{}
		}
		out = append(out, map[string]any{"name": k.name, "labels": l, "count": counts[k]})
	}
	s.Enqueue(map[string]any{"event": "counters", "properties": map[string]any{"counters": out}})
}

// Flush sends everything queued and returns how many events the collector took.
func (s *Sender) Flush(ctx context.Context) int {
	s.mu.Lock()
	events := s.queue
	s.queue = nil
	s.mu.Unlock()
	sent := 0
	for start := 0; start < len(events); start += MaxBatch {
		batch := events[start:min(start+MaxBatch, len(events))]
		if err := s.collector.Post(ctx, batch); err != nil {
			s.dropped(ctx, len(batch), err)
			continue
		}
		s.recovered(ctx)
		sent += len(batch)
	}
	return sent
}

// SendAll rolls the counters up and flushes.
func (s *Sender) SendAll(ctx context.Context) {
	s.RollUp()
	s.Flush(ctx)
}

// Run sends every FlushEvery until ctx ends.
func (s *Sender) Run(ctx context.Context, every time.Duration) {
	t := time.NewTicker(every)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			s.SendAll(ctx)
		}
	}
}

func (s *Sender) dropped(ctx context.Context, n int, err error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	now := s.now()
	s.droppedInOutage += n
	if s.failureLoggedAt == nil {
		s.log.WarnContext(ctx, "Dropped analytics events the collector did not accept", "count", n, "error", err)
		s.failureLoggedAt = &now
		return
	}
	s.droppedUnlogged += n
	if now.Sub(*s.failureLoggedAt) >= failureLogEvery {
		s.log.WarnContext(ctx, "The analytics collector is still not accepting events", "dropped", s.droppedUnlogged,
			"since", s.failureLoggedAt.UTC().Format(time.RFC3339), "error", err)
		s.failureLoggedAt, s.droppedUnlogged = &now, 0
	}
}

func (s *Sender) recovered(ctx context.Context) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.failureLoggedAt == nil {
		return
	}
	s.log.InfoContext(ctx, "The analytics collector accepts events again", "dropped", s.droppedInOutage)
	s.failureLoggedAt, s.droppedUnlogged, s.droppedInOutage = nil, 0, 0
}
