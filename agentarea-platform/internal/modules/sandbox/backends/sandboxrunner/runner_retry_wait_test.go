package sandboxrunner

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	redis "github.com/redis/go-redis/v9"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/sandboxcontrol"
)

// A runner waiting out a failed read stops as soon as it is asked to, not
// after its retry wait.
func TestRunnerStopsDuringItsRetryWait(t *testing.T) {
	server := miniredis.RunT(t)
	store, err := sandboxcontrol.NewRedisStore(redis.NewClient(&redis.Options{Addr: server.Addr(), MaxRetries: -1}), "runner-retry", time.Hour, testRunnerExecutionPolicy(), sandboxcontrol.WithEventStreams("retry.requests", "retry.events", "test"))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = store.RedisClient().Close() }()
	runner := New(Config{RequestStream: "retry.requests", EventStream: "retry.events", Block: 20 * time.Millisecond, ReclaimEvery: time.Hour}, store, &recordingSandboxExecutor{}, slog.New(slog.NewTextHandler(io.Discard, nil)))
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- runner.Run(ctx) }()
	waitFor(t, func() bool { return server.Exists("retry.requests") })

	server.Close()
	time.Sleep(100 * time.Millisecond)
	began := time.Now()
	cancel()
	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("Run() = %v, want context.Canceled", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Run did not return")
	}
	if took := time.Since(began); took > 300*time.Millisecond {
		t.Fatalf("Run took %v to stop: the retry wait ignores ctx", took)
	}
}
