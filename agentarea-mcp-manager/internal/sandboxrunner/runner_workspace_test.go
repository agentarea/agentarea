package sandboxrunner

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"log/slog"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	redis "github.com/go-redis/redis/v8"

	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/sandboxcontrol"
	"github.com/agentarea/mcp-manager/internal/warmpool"
	"github.com/agentarea/mcp-manager/internal/workspace"
)

func newSessionExecution(t *testing.T, runner *Runner) *sandboxcontrol.ExecutionRecord {
	t.Helper()
	record, err := runner.service.CreateExecution(context.Background(), sandboxcontrol.ExecutionCreateRequest{
		Runtime:     sandboxcontrol.RuntimeSelector{PackageInstall: runtimeinfo.PackageInstallAllowed},
		WorkspaceID: "workspace-1",
		TaskID:      "task-1",
		Command:     warmpool.ExecuteRequest{CommandBody: "echo ok"},
	})
	if err != nil {
		t.Fatalf("CreateExecution() error = %v", err)
	}
	return record
}

func firstRequestMessage(t *testing.T, runner *Runner, stream string) redis.XMessage {
	t.Helper()
	if err := runner.ensureConsumerGroup(context.Background()); err != nil {
		t.Fatal(err)
	}
	messages, err := runner.store.RedisClient().XRange(context.Background(), stream, "-", "+").Result()
	if err != nil || len(messages) != 1 {
		t.Fatalf("request messages = %d, error = %v", len(messages), err)
	}
	return messages[0]
}

func TestRunnerExecutesSessionCommandAndStoresOutputRefs(t *testing.T) {
	server := miniredis.RunT(t)
	store, err := sandboxcontrol.NewRedisStore("redis://"+server.Addr(), "runner-session", time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	repository := &recordingWorkspaceRepository{storedOutputs: map[string][]byte{}}
	executor := &recordingSandboxExecutor{result: &warmpool.ExecuteResponse{Stdout: "STDOUT-BODY", Stderr: "STDERR-BODY", ExitCode: 0}}
	runner := New(Config{RequestStream: "session.requests", EventStream: "session.events"}, store, executor, slog.New(slog.NewTextHandler(io.Discard, nil)))
	runner.workspaceRepository = repository

	ctx := context.Background()
	record := newSessionExecution(t, runner)
	if err := runner.handleMessage(ctx, firstRequestMessage(t, runner, "session.requests")); err != nil {
		t.Fatalf("handleMessage() error = %v", err)
	}

	if executor.executeCalls != 1 {
		t.Fatalf("ExecuteSandbox calls = %d, want 1", executor.executeCalls)
	}
	updated, err := runner.service.GetExecution(ctx, record.ID)
	if err != nil {
		t.Fatal(err)
	}
	if updated.Status != sandboxcontrol.ExecutionStatusCompleted {
		t.Fatalf("status = %q, want completed", updated.Status)
	}
	if updated.Result == nil || updated.Result.Stdout != "" || updated.Result.Stderr != "" ||
		updated.Result.StdoutRef == nil || updated.Result.StderrRef == nil {
		t.Fatalf("durable result is not refs-only: %#v", updated.Result)
	}
	if len(updated.OutputRefs) != 2 {
		t.Fatalf("output refs = %#v", updated.OutputRefs)
	}
	if string(repository.storedOutputs["stdout"]) != "STDOUT-BODY" || string(repository.storedOutputs["stderr"]) != "STDERR-BODY" {
		t.Fatalf("stored bodies = %#v", repository.storedOutputs)
	}
}

func TestRunnerNeverWritesOutputBodiesToRedis(t *testing.T) {
	server := miniredis.RunT(t)
	store, err := sandboxcontrol.NewRedisStore("redis://"+server.Addr(), "runner-canary", time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	repository := &recordingWorkspaceRepository{storedOutputs: map[string][]byte{}}
	executor := &recordingSandboxExecutor{result: &warmpool.ExecuteResponse{Stdout: "STDOUT-BODY-CANARY", Stderr: "STDERR-BODY-CANARY", ExitCode: 0}}
	runner := New(Config{RequestStream: "canary.requests", EventStream: "canary.events", Group: "canary-group"}, store, executor, slog.New(slog.NewTextHandler(io.Discard, nil)))
	runner.workspaceRepository = repository

	ctx := context.Background()
	record := newSessionExecution(t, runner)
	if err := runner.handleMessage(ctx, firstRequestMessage(t, runner, "canary.requests")); err != nil {
		t.Fatalf("handleMessage() error = %v", err)
	}
	raw, err := store.RedisClient().Get(ctx, "runner-canary:execution:"+record.ID).Result()
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(raw, "STDOUT-BODY-CANARY") || strings.Contains(raw, "STDERR-BODY-CANARY") {
		t.Fatalf("Redis record contains command output body: %s", raw)
	}
}

func TestRunnerMarksExecutionFailedWhenExecutorErrors(t *testing.T) {
	server := miniredis.RunT(t)
	store, err := sandboxcontrol.NewRedisStore("redis://"+server.Addr(), "runner-failed", time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	repository := &recordingWorkspaceRepository{}
	executor := &recordingSandboxExecutor{executeErr: errStub("executor failed")}
	runner := New(Config{RequestStream: "failed.requests", EventStream: "failed.events", Group: "failed-group"}, store, executor, slog.New(slog.NewTextHandler(io.Discard, nil)))
	runner.workspaceRepository = repository

	ctx := context.Background()
	record := newSessionExecution(t, runner)
	if err := runner.handleMessage(ctx, firstRequestMessage(t, runner, "failed.requests")); err != nil {
		t.Fatalf("handleMessage() error = %v", err)
	}
	updated, err := runner.service.GetExecution(ctx, record.ID)
	if err != nil {
		t.Fatal(err)
	}
	if updated.Status != sandboxcontrol.ExecutionStatusFailed || !strings.Contains(updated.Error, "executor failed") {
		t.Fatalf("execution = %#v", updated)
	}
	if repository.putCalls != 0 {
		t.Fatalf("output offload ran after executor error: %d", repository.putCalls)
	}
}

func TestRunnerCompletesWithoutOffloadWhenNoWorkspaceRepository(t *testing.T) {
	server := miniredis.RunT(t)
	store, err := sandboxcontrol.NewRedisStore("redis://"+server.Addr(), "runner-nobucket", time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	executor := &recordingSandboxExecutor{result: &warmpool.ExecuteResponse{Stdout: "unpersisted", Stderr: "also-unpersisted", ExitCode: 0}}
	runner := New(Config{RequestStream: "nobucket.requests", EventStream: "nobucket.events", Group: "nobucket-group"}, store, executor, slog.New(slog.NewTextHandler(io.Discard, nil)))
	runner.workspaceRepository = nil

	ctx := context.Background()
	record := newSessionExecution(t, runner)
	if err := runner.handleMessage(ctx, firstRequestMessage(t, runner, "nobucket.requests")); err != nil {
		t.Fatalf("handleMessage() error = %v", err)
	}
	updated, err := runner.service.GetExecution(ctx, record.ID)
	if err != nil {
		t.Fatal(err)
	}
	if updated.Status != sandboxcontrol.ExecutionStatusCompleted {
		t.Fatalf("status = %q, want completed", updated.Status)
	}
	if updated.Result == nil || updated.Result.Stdout != "" || updated.Result.Stderr != "" ||
		updated.Result.StdoutRef != nil || updated.Result.StderrRef != nil {
		t.Fatalf("result without a bucket must be body-free and ref-free: %#v", updated.Result)
	}
	if len(updated.OutputRefs) != 0 {
		t.Fatalf("output refs without a bucket = %#v", updated.OutputRefs)
	}
}

func TestRunnerReclaimsPendingMessageAndExecutesClaimedWork(t *testing.T) {
	server := miniredis.RunT(t)
	store, err := sandboxcontrol.NewRedisStore("redis://"+server.Addr(), "runner-reclaim", time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	repository := &recordingWorkspaceRepository{storedOutputs: map[string][]byte{}}
	executor := &recordingSandboxExecutor{}
	runner := New(
		Config{
			RequestStream: "reclaim.requests", EventStream: "reclaim.events",
			Group: "reclaim-group", Consumer: "live-runner", PendingIdle: time.Millisecond,
		},
		store,
		executor,
		slog.New(slog.NewTextHandler(io.Discard, nil)),
	)
	runner.workspaceRepository = repository

	ctx := context.Background()
	if err := runner.ensureConsumerGroup(ctx); err != nil {
		t.Fatal(err)
	}
	record := newSessionExecution(t, runner)
	if _, err := store.RedisClient().XReadGroup(ctx, &redis.XReadGroupArgs{
		Group: "reclaim-group", Consumer: "dead-runner", Streams: []string{"reclaim.requests", ">"}, Count: 1,
	}).Result(); err != nil {
		t.Fatal(err)
	}
	server.FastForward(time.Second)
	time.Sleep(5 * time.Millisecond)

	if err := runner.reclaimPending(ctx); err != nil {
		t.Fatal(err)
	}
	updated, err := runner.service.GetExecution(ctx, record.ID)
	if err != nil {
		t.Fatal(err)
	}
	if updated.Status != sandboxcontrol.ExecutionStatusCompleted || executor.executeCalls != 1 {
		t.Fatalf("reclaimed execution status = %q, executor calls = %d", updated.Status, executor.executeCalls)
	}
	pending, err := store.RedisClient().XPending(ctx, "reclaim.requests", "reclaim-group").Result()
	if err != nil {
		t.Fatal(err)
	}
	if pending.Count != 0 {
		t.Fatalf("pending messages = %d", pending.Count)
	}
}

func TestRunnerRefusesToRerunUncertainRunningExecution(t *testing.T) {
	server := miniredis.RunT(t)
	store, err := sandboxcontrol.NewRedisStore("redis://"+server.Addr(), "runner-uncertain", time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	repository := &recordingWorkspaceRepository{}
	executor := &recordingSandboxExecutor{}
	runner := New(
		Config{RequestStream: "uncertain.requests", EventStream: "uncertain.events", Group: "uncertain-group", Consumer: "recovery-runner", PendingIdle: time.Millisecond},
		store,
		executor,
		slog.New(slog.NewTextHandler(io.Discard, nil)),
	)
	runner.workspaceRepository = repository
	ctx := context.Background()
	if err := runner.ensureConsumerGroup(ctx); err != nil {
		t.Fatal(err)
	}
	record := newSessionExecution(t, runner)
	if _, err := store.RedisClient().XReadGroup(ctx, &redis.XReadGroupArgs{
		Group: "uncertain-group", Consumer: "dead-runner", Streams: []string{"uncertain.requests", ">"}, Count: 1,
	}).Result(); err != nil {
		t.Fatal(err)
	}
	if _, err := runner.service.ApplyExecutionEvent(ctx, record.ID, sandboxcontrol.ExecutionEventRequest{EventType: sandboxcontrol.EventTypeExecutionStarted}); err != nil {
		t.Fatal(err)
	}
	server.FastForward(time.Second)
	time.Sleep(5 * time.Millisecond)

	if err := runner.reclaimPending(ctx); err != nil {
		t.Fatal(err)
	}
	updated, err := runner.service.GetExecution(ctx, record.ID)
	if err != nil {
		t.Fatal(err)
	}
	if updated.Status != sandboxcontrol.ExecutionStatusFailed || !strings.Contains(updated.Error, "refusing to rerun") || executor.executeCalls != 0 {
		t.Fatalf("uncertain execution = %#v, executor calls = %d", updated, executor.executeCalls)
	}
}

type errStub string

func (e errStub) Error() string { return string(e) }

type recordingWorkspaceRepository struct {
	mu            sync.Mutex
	putCalls      int
	storedOutputs map[string][]byte
	putErr        error
}

func (r *recordingWorkspaceRepository) PutExecutionOutput(_ context.Context, workspaceID, taskID, executionID, stream string, content []byte) (workspace.Entry, error) {
	r.mu.Lock()
	r.putCalls++
	if r.storedOutputs != nil {
		r.storedOutputs[stream] = append([]byte(nil), content...)
	}
	r.mu.Unlock()
	if r.putErr != nil {
		return workspace.Entry{}, r.putErr
	}
	digest := sha256.Sum256(content)
	hash := hex.EncodeToString(digest[:])
	return workspace.Entry{
		RelativePath:        ".agentarea/executions/" + executionID + "/" + stream + ".txt",
		ObjectURI:           "s3://trusted/workspaces/" + workspaceID + "/tasks/" + taskID + "/objects/" + hash,
		ObjectVersionOrETag: "etag-output",
		SHA256:              hash,
		Size:                int64(len(content)),
		ContentType:         "text/plain; charset=utf-8",
		Mode:                0o600,
	}, nil
}

type recordingSandboxExecutor struct {
	executeErr   error
	executeCalls int
	result       *warmpool.ExecuteResponse
}

func (e *recordingSandboxExecutor) ExecuteSandbox(context.Context, warmpool.ExecuteRequest) (*warmpool.ExecuteResponse, error) {
	e.executeCalls++
	if e.executeErr != nil {
		return nil, e.executeErr
	}
	if e.result != nil {
		copied := *e.result
		return &copied, nil
	}
	return &warmpool.ExecuteResponse{ExitCode: 0}, nil
}
