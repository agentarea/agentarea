package sandboxrunner

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"

	"github.com/agentarea/mcp-manager/internal/sandboxcontrol"
)

// A Redis restart without persistence takes the request stream and its group
// with it. The running loop must recreate the group and take the next request
// instead of failing every read with NOGROUP until the process restarts.
func TestRunnerKeepsConsumingAfterRedisLosesItsGroup(t *testing.T) {
	server := miniredis.RunT(t)
	store, err := sandboxcontrol.NewRedisStore("redis://"+server.Addr(), "runner-lost", time.Hour, testRunnerExecutionPolicy(), sandboxcontrol.WithEventStreams("lost.requests", "lost.events", "test"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	runner := New(Config{RequestStream: "lost.requests", EventStream: "lost.events", Block: 20 * time.Millisecond}, store, &recordingSandboxExecutor{}, slog.New(slog.NewTextHandler(io.Discard, nil)))
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- runner.Run(ctx) }()
	t.Cleanup(func() {
		cancel()
		if err := <-done; !errors.Is(err, context.Canceled) {
			t.Errorf("Run() = %v, want context.Canceled", err)
		}
	})
	waitFor(t, func() bool { return server.Exists("lost.requests") })

	server.Del("lost.requests")
	time.Sleep(50 * time.Millisecond)
	record := newSessionExecution(t, runner)

	waitFor(t, func() bool {
		updated, err := runner.service.GetExecution(ctx, record.ID)
		return err == nil && updated.Status == sandboxcontrol.ExecutionStatusCompleted
	})
}

func waitFor(t *testing.T, condition func() bool) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for !condition() {
		if time.Now().After(deadline) {
			t.Fatal("condition not reached in time")
		}
		time.Sleep(10 * time.Millisecond)
	}
}
