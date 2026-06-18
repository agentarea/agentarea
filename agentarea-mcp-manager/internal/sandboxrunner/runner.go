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
	"github.com/agentarea/mcp-manager/internal/warmpool"
)

// SandboxExecutor runs a sandbox script on whatever data plane the backend owns:
// a Kubernetes warm pod (k8s backend) or the sandbox-executor container (docker
// backend). The runner is the control plane and never executes code itself — it
// always delegates across this boundary.
type SandboxExecutor interface {
	ExecuteSandbox(ctx context.Context, req warmpool.ExecuteRequest) (*warmpool.ExecuteResponse, error)
}

type Config struct {
	RequestStream string
	EventStream   string
	Group         string
	Consumer      string
	Block         time.Duration
	BatchSize     int64
}

type Runner struct {
	cfg      Config
	store    *sandboxcontrol.RedisStore
	service  *sandboxcontrol.Service
	executor SandboxExecutor
	logger   *slog.Logger
}

func New(cfg Config, store *sandboxcontrol.RedisStore, executor SandboxExecutor, logger *slog.Logger) *Runner {
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
	eventBus := sandboxcontrol.NewRedisEventBus(
		store.RedisClient(),
		cfg.RequestStream,
		cfg.EventStream,
		"agentarea.sandbox-runner",
	)
	return &Runner{
		cfg:      cfg,
		store:    store,
		service:  sandboxcontrol.NewService(store, eventBus),
		executor: executor,
		logger:   logger,
	}
}

func (r *Runner) Run(ctx context.Context) error {
	if err := r.ensureConsumerGroup(ctx); err != nil {
		return err
	}
	r.logger.Info("sandbox runner started",
		slog.String("stream", r.cfg.RequestStream),
		slog.String("group", r.cfg.Group),
		slog.String("consumer", r.cfg.Consumer))

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		streams, err := r.store.RedisClient().XReadGroup(ctx, &redis.XReadGroupArgs{
			Group:    r.cfg.Group,
			Consumer: r.cfg.Consumer,
			Streams:  []string{r.cfg.RequestStream, ">"},
			Count:    r.cfg.BatchSize,
			Block:    r.cfg.Block,
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
	if record.Status != sandboxcontrol.ExecutionStatusQueued {
		return r.ack(ctx, message.ID)
	}

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

	result, execErr := r.execute(ctx, record)
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

	outputRefs := artifactRefs(record.ID, result)
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

func (r *Runner) execute(ctx context.Context, record *sandboxcontrol.ExecutionRecord) (*warmpool.ExecuteResponse, error) {
	if _, err := r.service.ApplyExecutionEvent(ctx, record.ID, sandboxcontrol.ExecutionEventRequest{
		EventType: sandboxcontrol.EventTypeExecutionStarted,
		Metadata: map[string]string{
			"runner_consumer": r.cfg.Consumer,
		},
	}); err != nil {
		return nil, err
	}

	req := record.Command
	if req.WorkflowID == "" {
		req.WorkflowID = record.WorkflowID
	}
	if req.WorkflowID == "" {
		req.WorkflowID = record.ID
	}

	return r.executor.ExecuteSandbox(ctx, req)
}

func (r *Runner) ack(ctx context.Context, messageID string) error {
	if err := r.store.RedisClient().XAck(ctx, r.cfg.RequestStream, r.cfg.Group, messageID).Err(); err != nil {
		return fmt.Errorf("ack sandbox execution message %s: %w", messageID, err)
	}
	return nil
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

func artifactRefs(executionID string, result *warmpool.ExecuteResponse) []sandboxcontrol.SandboxObjectReference {
	if result == nil || len(result.Artifacts) == 0 {
		return nil
	}
	refs := make([]sandboxcontrol.SandboxObjectReference, 0, len(result.Artifacts))
	for _, artifact := range result.Artifacts {
		if artifact.Error != "" {
			continue
		}
		refs = append(refs, sandboxcontrol.SandboxObjectReference{
			URI:         fmt.Sprintf("sandbox-result://%s/%s", executionID, strings.TrimPrefix(artifact.Path, "/")),
			ContentType: artifact.ContentType,
			Size:        artifact.Size,
		})
	}
	return refs
}

func ConfigFromEnv() Config {
	return Config{
		RequestStream: getenv("SANDBOX_EXECUTION_REQUEST_STREAM", sandboxcontrol.DefaultExecutionRequestStream),
		EventStream:   getenv("SANDBOX_EXECUTION_EVENT_STREAM", sandboxcontrol.DefaultExecutionEventStream),
		Group:         getenv("SANDBOX_RUNNER_CONSUMER_GROUP", "agentarea-sandbox-runners"),
		Consumer:      getenv("SANDBOX_RUNNER_CONSUMER_NAME", defaultConsumerName()),
		Block:         durationEnv("SANDBOX_RUNNER_BLOCK_TIMEOUT", 5*time.Second),
		BatchSize:     int64(intEnv("SANDBOX_RUNNER_BATCH_SIZE", 1)),
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
