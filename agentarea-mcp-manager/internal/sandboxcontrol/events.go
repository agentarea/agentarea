package sandboxcontrol

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	redis "github.com/go-redis/redis/v8"
)

type EventBus interface {
	PublishRequested(ctx context.Context, record *ExecutionRecord) error
	PublishLifecycleEvent(ctx context.Context, record *ExecutionRecord, eventType string) error
}

type RedisEventBus struct {
	client        *redis.Client
	requestStream string
	eventStream   string
	source        string
}

func NewRedisEventBus(client *redis.Client, requestStream, eventStream, source string) *RedisEventBus {
	if requestStream == "" {
		requestStream = DefaultExecutionRequestStream
	}
	if eventStream == "" {
		eventStream = DefaultExecutionEventStream
	}
	if source == "" {
		source = "agentarea.mcp-manager.sandbox-control"
	}
	return &RedisEventBus{
		client:        client,
		requestStream: requestStream,
		eventStream:   eventStream,
		source:        source,
	}
}

func (b *RedisEventBus) PublishRequested(ctx context.Context, record *ExecutionRecord) error {
	return b.publish(ctx, b.requestStream, EventTypeExecutionRequested, record)
}

func (b *RedisEventBus) PublishLifecycleEvent(ctx context.Context, record *ExecutionRecord, eventType string) error {
	return b.publish(ctx, b.eventStream, eventType, record)
}

func (b *RedisEventBus) publish(ctx context.Context, stream, eventType string, record *ExecutionRecord) error {
	if b == nil || b.client == nil {
		return fmt.Errorf("sandbox event bus is not configured")
	}
	data := map[string]any{
		"execution_id": record.ID,
		"status":       record.Status,
	}
	if record.TaskID != "" {
		data["task_id"] = record.TaskID
	}
	if record.WorkspaceID != "" {
		data["workspace_id"] = record.WorkspaceID
	}
	if record.WorkspaceManifestRef != nil {
		data["workspace_manifest_ref"] = record.WorkspaceManifestRef
	}
	if len(record.OutputRefs) > 0 {
		data["output_refs"] = record.OutputRefs
		data["output_ref_count"] = len(record.OutputRefs)
	}
	event := CloudEvent{
		SpecVersion:     "1.0",
		Type:            eventType,
		Source:          b.source,
		ID:              newID("evt"),
		Time:            time.Now().UTC(),
		DataContentType: "application/json",
		CorrelationID:   record.ID,
		Data:            data,
	}
	payload, err := json.Marshal(event)
	if err != nil {
		return fmt.Errorf("encode sandbox event %s: %w", eventType, err)
	}
	if err := b.client.XAdd(ctx, &redis.XAddArgs{
		Stream: stream,
		Values: map[string]any{"event": string(payload)},
	}).Err(); err != nil {
		return fmt.Errorf("publish sandbox event %s to stream %s: %w", eventType, stream, err)
	}
	_ = b.client.Publish(ctx, stream, string(payload)).Err()
	return nil
}
