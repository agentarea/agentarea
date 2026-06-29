package events

import (
	"context"
	"encoding/json"
	"log/slog"
	"strings"
	"time"

	redis "github.com/go-redis/redis/v8"
	"github.com/google/uuid"
)

// Event bus contract (ADR-0018): events are XADDed to per-type Redis Streams
// in CloudEvents binary content mode. Envelope attributes become `ce_*` fields
// and the payload is a JSON string under `data`. The Python API consumes these
// via RedisStreamsEventBus — keep these constants in sync with the Python
// `topic_for(type)` mapping (`events:<type>`) and event-type strings.
const (
	eventSource = "agentarea-mcp-manager"

	statusChangedType = "agentarea.mcp.v1.MCPServerInstanceStatusChanged"
	errorType         = "agentarea.mcp.v1.MCPServerInstanceError"
)

func streamFor(eventType string) string { return "events:" + eventType }

// StatusUpdateEvent represents a container status update event
type StatusUpdateEvent struct {
	InstanceID  string    `json:"instance_id"`
	Name        string    `json:"name"`
	Status      string    `json:"status"`
	ContainerID string    `json:"container_id,omitempty"`
	URL         string    `json:"url,omitempty"`
	Error       string    `json:"error,omitempty"`
	Timestamp   time.Time `json:"timestamp"`
}

// ErrorEvent represents a container error event
type ErrorEvent struct {
	InstanceID string    `json:"instance_id"`
	Name       string    `json:"name"`
	Error      string    `json:"error"`
	Timestamp  time.Time `json:"timestamp"`
}

// EventPublisher handles publishing events to Redis
type EventPublisher struct {
	redisClient *redis.Client
	logger      *slog.Logger
}

// NewEventPublisher creates a new event publisher
func NewEventPublisher(redisURL string, logger *slog.Logger) *EventPublisher {
	var opts *redis.Options
	if parsed, err := redis.ParseURL(redisURL); err == nil {
		opts = parsed
	} else {
		var addr string
		if cutAddr, found := strings.CutPrefix(redisURL, "redis://"); found {
			addr = cutAddr
		} else {
			addr = redisURL
		}
		opts = &redis.Options{Addr: addr}
	}

	rdb := redis.NewClient(opts)

	return &EventPublisher{
		redisClient: rdb,
		logger:      logger,
	}
}

// buildEventFields encodes an event as Redis stream fields in CloudEvents
// binary content mode. `subject` is the partition key (empty -> omitted).
func buildEventFields(eventType, subject string, data any) (map[string]any, error) {
	payload, err := json.Marshal(data)
	if err != nil {
		return nil, err
	}

	fields := map[string]any{
		"ce_id":              uuid.NewString(),
		"ce_type":            eventType,
		"ce_source":          eventSource,
		"ce_time":            time.Now().UTC().Format(time.RFC3339),
		"ce_specversion":     "1.0",
		"ce_datacontenttype": "application/json",
		"data":               string(payload),
	}
	if subject != "" {
		fields["ce_subject"] = subject
	}
	return fields, nil
}

// publish XADDs the event to the stream for its type.
func (p *EventPublisher) publish(ctx context.Context, eventType, subject string, data any) error {
	fields, err := buildEventFields(eventType, subject, data)
	if err != nil {
		return err
	}
	return p.redisClient.XAdd(ctx, &redis.XAddArgs{
		Stream: streamFor(eventType),
		Values: fields,
	}).Err()
}

// PublishStatusUpdate publishes a container status update event
func (p *EventPublisher) PublishStatusUpdate(ctx context.Context, instanceID, name, status string, containerID, url string) error {
	event := StatusUpdateEvent{
		InstanceID:  instanceID,
		Name:        name,
		Status:      status,
		ContainerID: containerID,
		URL:         url,
		Timestamp:   time.Now(),
	}

	if err := p.publish(ctx, statusChangedType, instanceID, event); err != nil {
		p.logger.Error("Failed to publish status update event",
			slog.String("instance_id", instanceID),
			slog.String("status", status),
			slog.String("error", err.Error()))
		return err
	}

	p.logger.Info("Published status update event",
		slog.String("instance_id", instanceID),
		slog.String("name", name),
		slog.String("status", status),
		slog.String("container_id", containerID))

	return nil
}

// PublishError publishes a container error event
func (p *EventPublisher) PublishError(ctx context.Context, instanceID, name, errorMsg string) error {
	event := ErrorEvent{
		InstanceID: instanceID,
		Name:       name,
		Error:      errorMsg,
		Timestamp:  time.Now(),
	}

	if err := p.publish(ctx, errorType, instanceID, event); err != nil {
		p.logger.Error("Failed to publish error event",
			slog.String("instance_id", instanceID),
			slog.String("error", err.Error()))
		return err
	}

	p.logger.Info("Published error event",
		slog.String("instance_id", instanceID),
		slog.String("name", name),
		slog.String("error_msg", errorMsg))

	return nil
}

// PublishRunning publishes that a container is running
func (p *EventPublisher) PublishRunning(ctx context.Context, instanceID, name, containerID, url string) error {
	return p.PublishStatusUpdate(ctx, instanceID, name, "running", containerID, url)
}

// PublishStarting publishes that a container is starting
func (p *EventPublisher) PublishStarting(ctx context.Context, instanceID, name string) error {
	return p.PublishStatusUpdate(ctx, instanceID, name, "starting", "", "")
}

// PublishValidating publishes that a container is being validated
func (p *EventPublisher) PublishValidating(ctx context.Context, instanceID, name string) error {
	return p.PublishStatusUpdate(ctx, instanceID, name, "validating", "", "")
}

// PublishFailed publishes that a container failed to start
func (p *EventPublisher) PublishFailed(ctx context.Context, instanceID, name, errorMsg string) error {
	_ = p.PublishError(ctx, instanceID, name, errorMsg)
	return p.PublishStatusUpdate(ctx, instanceID, name, "failed", "", "")
}

// Close closes the Redis connection
func (p *EventPublisher) Close() error {
	return p.redisClient.Close()
}
