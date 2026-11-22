package service

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"sync/atomic"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
)

type hubBroker struct {
	events.Broker
	live *hubLive
}

func (b *hubBroker) OpenLive(context.Context) (events.LiveChannels, error) { return b.live, nil }

type hubLive struct {
	nexts  atomic.Int32
	closed atomic.Bool
}

func (*hubLive) Subscribe(context.Context, string) error   { return nil }
func (*hubLive) Unsubscribe(context.Context, string) error { return nil }
func (l *hubLive) Close() error                            { l.closed.Store(true); return nil }
func (l *hubLive) Next(context.Context, time.Duration) (string, map[string]string, bool, error) {
	l.nexts.Add(1)
	return "", nil, false, errors.New("redis is down")
}

func TestNoticeHubStopsWithItsRun(t *testing.T) {
	b := &hubBroker{live: &hubLive{}}
	h := newNoticeHub(b, slog.New(slog.NewTextHandler(io.Discard, nil)))
	ctx, cancel := context.WithCancel(context.Background())
	ran := make(chan error, 1)
	go func() { ran <- h.Run(ctx) }()

	q, leave, err := h.subscribe(context.Background(), "ws-1")
	if err != nil {
		t.Fatal(err)
	}
	defer leave()
	deadline := time.Now().Add(2 * time.Second)
	for b.live.nexts.Load() == 0 {
		if time.Now().After(deadline) {
			t.Fatal("the hub's loop never ran")
		}
		time.Sleep(time.Millisecond)
	}

	began := time.Now()
	cancel()
	select {
	case err := <-ran:
		if err != nil {
			t.Fatalf("Run: %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Run did not return after its context ended: the loop is still running")
	}
	if took := time.Since(began); took > 500*time.Millisecond {
		t.Fatalf("the hub took %v to stop: its retry wait ignores ctx", took)
	}
	if !b.live.closed.Load() {
		t.Fatal("the live channels were left open")
	}
	nexts := b.live.nexts.Load()
	time.Sleep(50 * time.Millisecond)
	if b.live.nexts.Load() != nexts {
		t.Fatal("the loop kept running after Run returned")
	}

	select {
	case _, ok := <-q:
		if ok {
			t.Fatal("an ended page received a notice")
		}
	case <-time.After(time.Second):
		t.Fatal("a page kept waiting after the hub stopped")
	}

	if _, _, err := h.subscribe(context.Background(), "ws-2"); !errors.Is(err, errHubClosed) {
		t.Fatalf("subscribe after shutdown: got %v, want errHubClosed", err)
	}
}
