package sandboxrunner

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"strconv"
	"strings"
	"time"

	redis "github.com/go-redis/redis/v8"

	"github.com/agentarea/mcp-manager/internal/sandboxcontrol"
	"github.com/agentarea/mcp-manager/internal/sandboxplacement"
	"github.com/agentarea/mcp-manager/internal/warmpool"
	"github.com/agentarea/mcp-manager/internal/workspace"
)

// SandboxExecutor runs a sandbox script on whatever data plane the backend owns:
// a Kubernetes warm pod (k8s backend) or the sandbox-executor container (docker
// backend). The runner is the control plane and never executes code itself — it
// always delegates across this boundary. It aliases sandboxplacement.Executor so
// existing call sites keep working while placement owns the "which sandbox" seam.
type SandboxExecutor = sandboxplacement.Executor

// workspaceRepository offloads command output to content-addressed object
// storage so only bounded refs travel through Redis. It is optional: when no
// bucket is configured the runner drops the bodies and emits no refs.
type workspaceRepository interface {
	PutExecutionOutput(ctx context.Context, workspaceID, taskID, executionID, stream string, content []byte) (workspace.Entry, error)
}

type Config struct {
	RequestStream  string
	EventStream    string
	Group          string
	Consumer       string
	Block          time.Duration
	BatchSize      int64
	PendingIdle    time.Duration
	ReclaimEvery   time.Duration
	HeartbeatEvery time.Duration
}

type Runner struct {
	cfg                 Config
	store               *sandboxcontrol.RedisStore
	service             *sandboxcontrol.Service
	placer              sandboxplacement.Placer
	logger              *slog.Logger
	workspaceRepository workspaceRepository
}

// New builds a Runner that places every execution on a single "default" data
// plane. It is the convenience constructor for single-backend deployments and
// tests; use NewWithPlacer to register multiple region/isolation-scoped targets.
func New(cfg Config, store *sandboxcontrol.RedisStore, executor SandboxExecutor, logger *slog.Logger) *Runner {
	placer, err := sandboxplacement.NewRegistry(sandboxplacement.Target{
		Executor:     executor,
		Capabilities: sandboxplacement.Capabilities{Name: "default"},
	})
	if err != nil {
		// A single named target only fails when the executor is nil, which is a
		// programming error at the call site. Fail loudly rather than run blind.
		panic(fmt.Sprintf("sandboxrunner.New: invalid default placement target: %v", err))
	}
	return NewWithPlacer(cfg, store, placer, logger)
}

// NewWithPlacer builds a Runner that resolves the data plane per execution
// through the given Placer. This is the composition-root constructor: it lets
// the control plane route tasks to different sandboxes by placement rules.
func NewWithPlacer(cfg Config, store *sandboxcontrol.RedisStore, placer sandboxplacement.Placer, logger *slog.Logger) *Runner {
	if cfg.RequestStream == "" {
		cfg.RequestStream = sandboxcontrol.DefaultExecutionRequestStream
	}
	if cfg.EventStream == "" {
		cfg.EventStream = sandboxcontrol.DefaultExecutionEventStream
	}
	if cfg.Group == "" {
		cfg.Group = "agentarea-sandbox-runners"
	}
	if cfg.Consumer == "" {
		cfg.Consumer = defaultConsumerName()
	}
	if cfg.Block <= 0 {
		cfg.Block = 5 * time.Second
	}
	if cfg.BatchSize <= 0 {
		cfg.BatchSize = 1
	}
	if cfg.PendingIdle <= 0 {
		cfg.PendingIdle = 2 * time.Minute
	}
	if cfg.ReclaimEvery <= 0 {
		cfg.ReclaimEvery = 15 * time.Second
	}
	if cfg.HeartbeatEvery <= 0 {
		cfg.HeartbeatEvery = 30 * time.Second
	}
	service, err := sandboxcontrol.NewService(store, store.ExecutionPolicy())
	if err != nil {
		panic(fmt.Sprintf("invalid sandbox execution policy: %v", err))
	}
	runner := &Runner{
		cfg:     cfg,
		store:   store,
		service: service,
		placer:  placer,
		logger:  logger,
	}
	return runner
}

func NewWithWorkspaceRepository(cfg Config, store *sandboxcontrol.RedisStore, executor SandboxExecutor, logger *slog.Logger, repository *workspace.Repository) *Runner {
	runner := New(cfg, store, executor, logger)
	runner.workspaceRepository = repository
	return runner
}

func NewWithPlacerAndWorkspaceRepository(
	cfg Config,
	store *sandboxcontrol.RedisStore,
	placer sandboxplacement.Placer,
	logger *slog.Logger,
	repository workspaceRepository,
) *Runner {
	runner := NewWithPlacer(cfg, store, placer, logger)
	runner.workspaceRepository = repository
	return runner
}

func (r *Runner) Run(ctx context.Context) error {
	if err := r.ensureConsumerGroup(ctx); err != nil {
		return err
	}
	r.logger.Info("sandbox runner started",
		slog.String("stream", r.cfg.RequestStream),
		slog.String("group", r.cfg.Group),
		slog.String("consumer", r.cfg.Consumer))

	nextReclaim := time.Now()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		if !time.Now().Before(nextReclaim) {
			if err := r.reclaimPending(ctx); err != nil {
				if ctx.Err() != nil {
					return ctx.Err()
				}
				r.logger.Error("sandbox runner pending recovery failed", slog.String("error", err.Error()))
			}
			nextReclaim = time.Now().Add(r.cfg.ReclaimEvery)
		}

		block := r.cfg.Block
		if untilReclaim := time.Until(nextReclaim); untilReclaim > 0 && untilReclaim < block {
			block = untilReclaim
		}
		streams, err := r.store.RedisClient().XReadGroup(ctx, &redis.XReadGroupArgs{
			Group:    r.cfg.Group,
			Consumer: r.cfg.Consumer,
			Streams:  []string{r.cfg.RequestStream, ">"},
			Count:    r.cfg.BatchSize,
			Block:    block,
		}).Result()
		if errors.Is(err, redis.Nil) {
			continue
		}
		if err != nil {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			if isNoGroupError(err) {
				r.logger.Warn("sandbox runner consumer group missing; recreating",
					slog.String("stream", r.cfg.RequestStream),
					slog.String("group", r.cfg.Group),
					slog.String("error", err.Error()))
				if groupErr := r.ensureConsumerGroup(ctx); groupErr != nil {
					r.logger.Error("sandbox runner consumer group recreate failed",
						slog.String("error", groupErr.Error()))
					time.Sleep(time.Second)
				}
				continue
			}
			r.logger.Error("sandbox runner read failed", slog.String("error", err.Error()))
			time.Sleep(time.Second)
			continue
		}

		for _, stream := range streams {
			for _, message := range stream.Messages {
				if err := r.handleMessage(ctx, message); err != nil {
					r.logger.Error("sandbox execution message failed",
						slog.String("message_id", message.ID),
						slog.String("error", err.Error()))
				}
			}
		}
	}
}

func (r *Runner) ensureConsumerGroup(ctx context.Context) error {
	err := r.store.RedisClient().XGroupCreateMkStream(ctx, r.cfg.RequestStream, r.cfg.Group, "0").Err()
	if err == nil || strings.Contains(err.Error(), "BUSYGROUP") {
		return nil
	}
	return fmt.Errorf("create sandbox runner consumer group: %w", err)
}

func isNoGroupError(err error) bool {
	return err != nil && strings.Contains(err.Error(), "NOGROUP")
}

func (r *Runner) handleMessage(ctx context.Context, message redis.XMessage) error {
	stopHeartbeat := r.startPendingHeartbeat(ctx, message.ID)
	defer stopHeartbeat()

	payload, err := eventPayload(message)
	if err != nil {
		return err
	}
	eventRecord, err := sandboxcontrol.ExecutionFromCloudEvent([]byte(payload))
	if err != nil {
		return err
	}
	record, err := r.service.GetExecution(ctx, eventRecord.ID)
	if err != nil {
		return err
	}
	if isTerminalStatus(record.Status) {
		return r.ack(ctx, message.ID)
	}
	if record.Status == sandboxcontrol.ExecutionStatusQueued {
		r.logger.Info("sandbox execution claimed",
			slog.String("execution_id", record.ID),
			slog.String("workflow_id", record.WorkflowID),
			slog.String("message_id", message.ID))
		record, err = r.service.ApplyExecutionEvent(ctx, record.ID, sandboxcontrol.ExecutionEventRequest{
			EventType: sandboxcontrol.EventTypeExecutionClaimed,
			Metadata: map[string]string{
				"runner_consumer": r.cfg.Consumer,
			},
		})
		if err != nil {
			return err
		}
	}
	if record.Status == sandboxcontrol.ExecutionStatusRunning {
		return r.recoverRunningExecution(ctx, message.ID, record)
	}
	if record.Status != sandboxcontrol.ExecutionStatusClaimed {
		return r.failAndAck(ctx, message.ID, record, "execution has an invalid non-terminal state; refusing to run")
	}

	result, outputRefs, execErr := r.execute(ctx, record)
	if execErr != nil {
		r.logger.Error("sandbox execution failed",
			slog.String("execution_id", record.ID),
			slog.String("workflow_id", record.WorkflowID),
			slog.String("error", execErr.Error()))
		_, markErr := r.service.ApplyExecutionEvent(ctx, record.ID, sandboxcontrol.ExecutionEventRequest{
			EventType: sandboxcontrol.EventTypeExecutionFailed,
			Error:     execErr.Error(),
			Metadata: map[string]string{
				"runner_consumer": r.cfg.Consumer,
			},
		})
		if markErr != nil {
			return fmt.Errorf("execution failed: %v; additionally failed to mark failed: %w", execErr, markErr)
		}
		return r.ack(ctx, message.ID)
	}

	_, err = r.service.ApplyExecutionEvent(ctx, record.ID, sandboxcontrol.ExecutionEventRequest{
		EventType:  sandboxcontrol.EventTypeExecutionCompleted,
		OutputRefs: outputRefs,
		Result:     result,
		Metadata: map[string]string{
			"runner_consumer": r.cfg.Consumer,
		},
	})
	if err != nil {
		return err
	}
	r.logger.Info("sandbox execution completed",
		slog.String("execution_id", record.ID),
		slog.String("workflow_id", record.WorkflowID),
		slog.Int("exit_code", result.ExitCode),
		slog.Int64("execution_time_ms", result.ExecutionTimeMs))
	return r.ack(ctx, message.ID)
}

func (r *Runner) execute(ctx context.Context, record *sandboxcontrol.ExecutionRecord) (*warmpool.ExecuteResponse, []workspace.Entry, error) {
	started, err := r.service.ApplyExecutionEvent(ctx, record.ID, sandboxcontrol.ExecutionEventRequest{
		EventType: sandboxcontrol.EventTypeExecutionStarted,
		Metadata: map[string]string{
			"runner_consumer": r.cfg.Consumer,
		},
	})
	if err != nil {
		return nil, nil, err
	}
	if started.ExecutionExpiresAt == nil {
		return nil, nil, fmt.Errorf("running sandbox execution has no server deadline")
	}
	executionCtx, cancelExecution := context.WithDeadline(ctx, *started.ExecutionExpiresAt)
	defer cancelExecution()

	req := record.Command
	req.TaskID = record.TaskID
	req.WorkspaceID = record.WorkspaceID
	if req.WorkflowID == "" {
		req.WorkflowID = record.WorkflowID
	}
	if req.WorkflowID == "" {
		req.WorkflowID = record.ID
	}

	// Placement is a control-plane decision: the record's runtime selector says
	// where the task MAY run (e.g. a region), and the placer resolves that to a
	// concrete data plane. Refusing to run is correct when no target qualifies —
	// we never silently fall back to the wrong sandbox.
	target, err := r.placer.Select(executionCtx, sandboxplacement.Constraints{
		Region: record.Runtime.Region,
	})
	if err != nil {
		return nil, nil, err
	}
	r.logger.Info("sandbox execution placed",
		slog.String("execution_id", record.ID),
		slog.String("sandbox_target", target.Capabilities.Name),
		slog.String("sandbox_region", target.Capabilities.Region))

	result, err := target.Executor.ExecuteSandbox(executionCtx, req)
	if err != nil {
		return nil, nil, err
	}

	// Command output never travels inline through Redis. When object storage is
	// configured each stream is persisted as an immutable, content-addressed
	// ref; without a bucket the bodies are dropped and no refs are emitted.
	stdout, stderr := result.Stdout, result.Stderr
	result.Stdout = ""
	result.Stderr = ""
	if r.workspaceRepository == nil {
		return result, nil, nil
	}
	stdoutRef, err := r.workspaceRepository.PutExecutionOutput(executionCtx, record.WorkspaceID, record.TaskID, record.ID, "stdout", []byte(stdout))
	if err != nil {
		return nil, nil, fmt.Errorf("persist stdout: %w", err)
	}
	stderrRef, err := r.workspaceRepository.PutExecutionOutput(executionCtx, record.WorkspaceID, record.TaskID, record.ID, "stderr", []byte(stderr))
	if err != nil {
		return nil, nil, fmt.Errorf("persist stderr: %w", err)
	}
	result.StdoutRef = &stdoutRef
	result.StderrRef = &stderrRef
	return result, []workspace.Entry{stdoutRef, stderrRef}, nil
}

func (r *Runner) ack(ctx context.Context, messageID string) error {
	if err := r.store.RedisClient().XAck(ctx, r.cfg.RequestStream, r.cfg.Group, messageID).Err(); err != nil {
		return fmt.Errorf("ack sandbox execution message %s: %w", messageID, err)
	}
	return nil
}

func (r *Runner) reclaimPending(ctx context.Context) error {
	pending, err := r.store.RedisClient().XPendingExt(ctx, &redis.XPendingExtArgs{
		Stream: r.cfg.RequestStream,
		Group:  r.cfg.Group,
		Idle:   r.cfg.PendingIdle,
		Start:  "-",
		End:    "+",
		Count:  r.cfg.BatchSize,
	}).Result()
	if errors.Is(err, redis.Nil) {
		return nil
	}
	if err != nil {
		if isNoGroupError(err) {
			return r.ensureConsumerGroup(ctx)
		}
		return fmt.Errorf("reclaim pending sandbox executions: %w", err)
	}
	if len(pending) == 0 {
		return nil
	}
	messageIDs := make([]string, 0, len(pending))
	for _, entry := range pending {
		messageIDs = append(messageIDs, entry.ID)
	}
	messages, err := r.store.RedisClient().XClaim(ctx, &redis.XClaimArgs{
		Stream:   r.cfg.RequestStream,
		Group:    r.cfg.Group,
		Consumer: r.cfg.Consumer,
		MinIdle:  r.cfg.PendingIdle,
		Messages: messageIDs,
	}).Result()
	if err != nil {
		return fmt.Errorf("claim pending sandbox executions: %w", err)
	}
	for _, message := range messages {
		r.logger.Info("sandbox execution pending message reclaimed",
			slog.String("message_id", message.ID),
			slog.String("consumer", r.cfg.Consumer))
		if err := r.handleMessage(ctx, message); err != nil {
			return err
		}
	}
	return nil
}

func (r *Runner) startPendingHeartbeat(parent context.Context, messageID string) func() {
	ctx, cancel := context.WithCancel(parent)
	done := make(chan struct{})
	go func() {
		defer close(done)
		ticker := time.NewTicker(r.cfg.HeartbeatEvery)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				if err := r.store.RedisClient().XClaim(ctx, &redis.XClaimArgs{
					Stream:   r.cfg.RequestStream,
					Group:    r.cfg.Group,
					Consumer: r.cfg.Consumer,
					MinIdle:  0,
					Messages: []string{messageID},
				}).Err(); err != nil && ctx.Err() == nil {
					r.logger.Warn("sandbox execution pending heartbeat failed",
						slog.String("message_id", messageID),
						slog.String("error", err.Error()))
				}
			}
		}
	}()
	return func() {
		cancel()
		<-done
	}
}

// recoverRunningExecution handles a message redelivered for an execution that
// was already running. The previous runner died mid-execution with an unknown
// outcome, so rerunning it is unsafe; refuse rather than risk a double run.
func (r *Runner) recoverRunningExecution(ctx context.Context, messageID string, record *sandboxcontrol.ExecutionRecord) error {
	return r.failAndAck(ctx, messageID, record, "execution was interrupted before a durable result was recorded; refusing to rerun")
}

func (r *Runner) failAndAck(ctx context.Context, messageID string, record *sandboxcontrol.ExecutionRecord, reason string) error {
	if _, err := r.service.ApplyExecutionEvent(ctx, record.ID, sandboxcontrol.ExecutionEventRequest{
		EventType: sandboxcontrol.EventTypeExecutionFailed,
		Error:     reason,
		Metadata: map[string]string{
			"runner_consumer": r.cfg.Consumer,
			"runner_phase":    "recovery_failed",
		},
	}); err != nil {
		return err
	}
	return r.ack(ctx, messageID)
}

func isTerminalStatus(status string) bool {
	return status == sandboxcontrol.ExecutionStatusCompleted ||
		status == sandboxcontrol.ExecutionStatusFailed ||
		status == sandboxcontrol.ExecutionStatusCancelled
}

func eventPayload(message redis.XMessage) (string, error) {
	value, ok := message.Values["event"]
	if !ok {
		return "", fmt.Errorf("sandbox execution message %s has no event field", message.ID)
	}
	switch typed := value.(type) {
	case string:
		return typed, nil
	case []byte:
		return string(typed), nil
	default:
		return fmt.Sprint(typed), nil
	}
}

func ConfigFromEnv() Config {
	return Config{
		RequestStream:  getenv("SANDBOX_EXECUTION_REQUEST_STREAM", sandboxcontrol.DefaultExecutionRequestStream),
		EventStream:    getenv("SANDBOX_EXECUTION_EVENT_STREAM", sandboxcontrol.DefaultExecutionEventStream),
		Group:          getenv("SANDBOX_RUNNER_CONSUMER_GROUP", "agentarea-sandbox-runners"),
		Consumer:       getenv("SANDBOX_RUNNER_CONSUMER_NAME", defaultConsumerName()),
		Block:          durationEnv("SANDBOX_RUNNER_BLOCK_TIMEOUT", 5*time.Second),
		BatchSize:      int64(intEnv("SANDBOX_RUNNER_BATCH_SIZE", 1)),
		PendingIdle:    durationEnv("SANDBOX_RUNNER_PENDING_IDLE", 2*time.Minute),
		ReclaimEvery:   durationEnv("SANDBOX_RUNNER_RECLAIM_INTERVAL", 15*time.Second),
		HeartbeatEvery: durationEnv("SANDBOX_RUNNER_PENDING_HEARTBEAT", 30*time.Second),
	}
}

func defaultConsumerName() string {
	hostname, err := os.Hostname()
	if err != nil || hostname == "" {
		return "sandbox-runner"
	}
	return hostname
}

func getenv(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

func durationEnv(name string, fallback time.Duration) time.Duration {
	value := os.Getenv(name)
	if value == "" {
		return fallback
	}
	duration, err := time.ParseDuration(value)
	if err != nil {
		return fallback
	}
	return duration
}

func intEnv(name string, fallback int) int {
	value := os.Getenv(name)
	if value == "" {
		return fallback
	}
	parsed, err := strconv.Atoi(value)
	if err != nil || parsed <= 0 {
		return fallback
	}
	return parsed
}
