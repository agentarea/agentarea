package sandboxrunner

import (
	"context"
	"io"
	"log/slog"
	"strings"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"

	"github.com/agentarea/mcp-manager/internal/sandboxcontrol"
	"github.com/agentarea/mcp-manager/internal/sandboxplacement"
	"github.com/agentarea/mcp-manager/internal/warmpool"
)

const testExecutionTimeoutSeconds = 1800

func testRunnerExecutionPolicy() sandboxcontrol.ExecutionPolicy {
	return sandboxcontrol.ExecutionPolicy{
		DefaultTimeoutSeconds: 120,
		MaxTimeoutSeconds:     testExecutionTimeoutSeconds,
		QueueTimeout:          5 * time.Minute,
		CompletionGrace:       time.Minute,
	}
}

func regionExecution(t *testing.T, runner *Runner, taskID, region string) *sandboxcontrol.ExecutionRecord {
	t.Helper()
	record, err := runner.service.CreateExecution(context.Background(), sandboxcontrol.ExecutionCreateRequest{
		Runtime:     sandboxcontrol.RuntimeSelector{Region: region},
		WorkspaceID: "workspace-1",
		TaskID:      taskID,
		Command:     warmpool.ExecuteRequest{CommandBody: "echo ok"},
	})
	if err != nil {
		t.Fatalf("CreateExecution() error = %v", err)
	}
	return record
}

// The runner must route an execution to the data plane whose declared region
// matches the task's runtime selector — the control plane owns "which sandbox".
func TestRunnerRoutesExecutionToMatchingRegion(t *testing.T) {
	server := miniredis.RunT(t)
	store, err := sandboxcontrol.NewRedisStore("redis://"+server.Addr(), "runner-place-ok", time.Hour, testRunnerExecutionPolicy(), sandboxcontrol.WithEventStreams("place-ok.requests", "place-ok.events", "test"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	euExec := &recordingSandboxExecutor{result: &warmpool.ExecuteResponse{ExitCode: 0}}
	usExec := &recordingSandboxExecutor{result: &warmpool.ExecuteResponse{ExitCode: 0}}
	placer, err := sandboxplacement.NewRegistry(
		sandboxplacement.Target{Executor: euExec, Capabilities: sandboxplacement.Capabilities{Name: "k8s-eu", Region: "eu-central"}},
		sandboxplacement.Target{Executor: usExec, Capabilities: sandboxplacement.Capabilities{Name: "k8s-us", Region: "us-east"}},
	)
	if err != nil {
		t.Fatal(err)
	}
	runner := NewWithPlacer(
		Config{RequestStream: "place-ok.requests", EventStream: "place-ok.events", Group: "place-ok-group"},
		store, placer, slog.New(slog.NewTextHandler(io.Discard, nil)),
	)

	ctx := context.Background()
	record := regionExecution(t, runner, "task-us", "us-east")
	if err := runner.handleMessage(ctx, firstRequestMessage(t, runner, "place-ok.requests")); err != nil {
		t.Fatalf("handleMessage() error = %v", err)
	}

	if usExec.executeCalls != 1 || euExec.executeCalls != 0 {
		t.Fatalf("routing sent work to the wrong region: us=%d eu=%d", usExec.executeCalls, euExec.executeCalls)
	}
	updated, err := runner.service.GetExecution(ctx, record.ID)
	if err != nil {
		t.Fatal(err)
	}
	if updated.Status != sandboxcontrol.ExecutionStatusCompleted {
		t.Fatalf("status = %q, want completed", updated.Status)
	}
}

// A task pinned to a region no target serves must fail — never silently run in
// another region. This is the residency invariant enforced at the control plane.
func TestRunnerFailsExecutionWhenNoRegionTarget(t *testing.T) {
	server := miniredis.RunT(t)
	store, err := sandboxcontrol.NewRedisStore("redis://"+server.Addr(), "runner-place-fail", time.Hour, testRunnerExecutionPolicy(), sandboxcontrol.WithEventStreams("place-fail.requests", "place-fail.events", "test"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	euExec := &recordingSandboxExecutor{result: &warmpool.ExecuteResponse{ExitCode: 0}}
	placer, err := sandboxplacement.NewRegistry(
		sandboxplacement.Target{Executor: euExec, Capabilities: sandboxplacement.Capabilities{Name: "k8s-eu", Region: "eu-central"}},
	)
	if err != nil {
		t.Fatal(err)
	}
	runner := NewWithPlacer(
		Config{RequestStream: "place-fail.requests", EventStream: "place-fail.events", Group: "place-fail-group"},
		store, placer, slog.New(slog.NewTextHandler(io.Discard, nil)),
	)

	ctx := context.Background()
	record := regionExecution(t, runner, "task-ap", "ap-south")
	if err := runner.handleMessage(ctx, firstRequestMessage(t, runner, "place-fail.requests")); err != nil {
		t.Fatalf("handleMessage() error = %v", err)
	}

	if euExec.executeCalls != 0 {
		t.Fatalf("execution ran on a non-matching region target: eu=%d", euExec.executeCalls)
	}
	updated, err := runner.service.GetExecution(ctx, record.ID)
	if err != nil {
		t.Fatal(err)
	}
	if updated.Status != sandboxcontrol.ExecutionStatusFailed || !strings.Contains(updated.Error, "no sandbox target satisfies") {
		t.Fatalf("expected fail-hard placement, got status=%q error=%q", updated.Status, updated.Error)
	}
}
