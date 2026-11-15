package lifecycle

import (
	"context"
	"errors"
	"slices"
	"sync"
	"testing"
	"time"
)

type journal struct {
	mu    sync.Mutex
	steps []string
}

func (j *journal) add(s string) {
	j.mu.Lock()
	defer j.mu.Unlock()
	j.steps = append(j.steps, s)
}

func (j *journal) get() []string {
	j.mu.Lock()
	defer j.mu.Unlock()
	return slices.Clone(j.steps)
}

func recorded(j *journal, name string, startErr error) Component {
	return Func(name,
		func(context.Context) error { j.add("start " + name); return startErr },
		func(context.Context) error { j.add("stop " + name); return nil })
}

func TestStartsInOrderStopsInReverse(t *testing.T) {
	j := &journal{}
	g := NewGroup(Options{StartupTimeout: time.Second, ShutdownTimeout: time.Second})
	g.Add(recorded(j, "db", nil), recorded(j, "events", nil), recorded(j, "http", nil))
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error)
	go func() { done <- g.Run(ctx) }()
	time.Sleep(20 * time.Millisecond)
	cancel()
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	want := []string{"start db", "start events", "start http", "stop http", "stop events", "stop db"}
	if !slices.Equal(j.get(), want) {
		t.Fatalf("got %v", j.get())
	}
}

func TestStartFailureStopsWhatStarted(t *testing.T) {
	j := &journal{}
	boom := errors.New("boom")
	g := NewGroup(Options{})
	g.Add(recorded(j, "db", nil), recorded(j, "events", boom), recorded(j, "http", nil))
	err := g.Run(context.Background())
	var se *StartError
	if !errors.As(err, &se) || se.Component != "events" || !errors.Is(err, boom) {
		t.Fatalf("got %v", err)
	}
	want := []string{"start db", "start events", "stop db"}
	if !slices.Equal(j.get(), want) {
		t.Fatalf("got %v", j.get())
	}
}

func TestLoopReturningEarlyFailsTheGroup(t *testing.T) {
	j := &journal{}
	g := NewGroup(Options{ShutdownTimeout: time.Second})
	g.Add(recorded(j, "db", nil), Loop("poller", func(context.Context) error { return errors.New("lost redis") }))
	err := g.Run(context.Background())
	var fe *FailedError
	if !errors.As(err, &fe) || fe.Component != "poller" {
		t.Fatalf("got %v", err)
	}
	if got := j.get(); got[len(got)-1] != "stop db" {
		t.Fatalf("db not stopped: %v", got)
	}
}

func TestLoopReturningNilEarlyIsAFailure(t *testing.T) {
	g := NewGroup(Options{})
	g.Add(Loop("relay", func(context.Context) error { return nil }))
	var fe *FailedError
	if err := g.Run(context.Background()); !errors.As(err, &fe) {
		t.Fatalf("got %v", err)
	}
}

func TestLoopStopsOnCancel(t *testing.T) {
	g := NewGroup(Options{ShutdownTimeout: time.Second})
	g.Add(Loop("consumer", func(ctx context.Context) error { <-ctx.Done(); return ctx.Err() }))
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	if err := g.Run(ctx); err != nil {
		t.Fatal(err)
	}
}

func TestShutdownIsBounded(t *testing.T) {
	g := NewGroup(Options{ShutdownTimeout: 30 * time.Millisecond})
	release := make(chan struct{})
	defer close(release)
	g.Add(Loop("stuck", func(context.Context) error { <-release; return nil }))
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
	defer cancel()
	began := time.Now()
	err := g.Run(ctx)
	var se *StopError
	if !errors.As(err, &se) || se.Component != "stuck" {
		t.Fatalf("got %v", err)
	}
	if time.Since(began) > time.Second {
		t.Fatal("shutdown not bounded")
	}
}
