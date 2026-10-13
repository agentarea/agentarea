package sandboxrunner

import (
	"context"
	"io"
	"log/slog"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"

	"github.com/agentarea/mcp-manager/internal/sandboxcontrol"
	"github.com/agentarea/mcp-manager/internal/warmpool"
)

// blockingSandboxExecutor runs until its context ends, as a long command does
// until the data plane is told to stop it.
type blockingSandboxExecutor struct {
	started chan struct{}
	stopped chan error
}

func (e *blockingSandboxExecutor) ExecuteSandbox(ctx context.Context, _ warmpool.ExecuteRequest) (*warmpool.ExecuteResponse, error) {
	close(e.started)
	<-ctx.Done()
	e.stopped <- ctx.Err()
	return nil, ctx.Err()
}

func TestRunnerStopsARunningCommandWhenItsCallerCancels(t *testing.T) {
	server := miniredis.RunT(t)
	store, err := sandboxcontrol.NewRedisStore("redis://"+server.Addr(), "runner-cancel", time.Hour, testRunnerExecutionPolicy(), sandboxcontrol.WithEventStreams("cancel.requests", "cancel.events", "test"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	executor := &blockingSandboxExecutor{started: make(chan struct{}), stopped: make(chan error, 1)}
	runner := New(Config{
		RequestStream: "cancel.requests", EventStream: "cancel.events", Group: "cancel-group",
		CancelPollEvery: 20 * time.Millisecond,
	}, store, executor, slog.New(slog.NewTextHandler(io.Discard, nil)))

	ctx := context.Background()
	record := newSessionExecution(t, runner)
	message := firstRequestMessage(t, runner, "cancel.requests")
	handled := make(chan error, 1)
	go func() { handled <- runner.handleMessage(ctx, message) }()

	select {
	case <-executor.started:
	case <-time.After(5 * time.Second):
		t.Fatal("the command never started")
	}
	if _, err := runner.service.CancelExecution(ctx, record.ID, "the run was stopped"); err != nil {
		t.Fatalf("CancelExecution() error = %v", err)
	}

	select {
	case stopErr := <-executor.stopped:
		if stopErr != context.Canceled {
			t.Fatalf("command stopped with %v, want context.Canceled", stopErr)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("the running command was not stopped")
	}
	if err := <-handled; err != nil {
		t.Fatalf("handleMessage() error = %v", err)
	}
	updated, err := runner.service.GetExecution(ctx, record.ID)
	if err != nil {
		t.Fatal(err)
	}
	if updated.Status != sandboxcontrol.ExecutionStatusCancelled {
		t.Fatalf("status = %q (error %q), want cancelled", updated.Status, updated.Error)
	}
}
