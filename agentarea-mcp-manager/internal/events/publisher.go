package events

import (
	"context"
	"encoding/json"
	"log/slog"
	"strings"
	"time"

	redis "github.com/go-redis/redis/v8"
)

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

	// Wrap in FastStream message format to match the API's expected structure
	eventData := map[string]any{
		"event_id":   generateEventID(),
		"timestamp":  event.Timestamp.Format(time.RFC3339),
		"event_type": "MCPServerInstanceStatusChanged",
		"data":       event,
	}

	message := map[string]any{
		"data":    eventData,
		"headers": map[string]any{},
	}

	eventBytes, err := json.Marshal(message)
	if err != nil {
		p.logger.Error("Failed to marshal status update event",
			slog.String("instance_id", instanceID),
			slog.String("error", err.Error()))
		return err
	}

	err = p.redisClient.Publish(ctx, "MCPServerInstanceStatusChanged", string(eventBytes)).Err()
	if err != nil {
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

	// Wrap in FastStream message format
	eventData := map[string]any{
		"event_id":   generateEventID(),
		"timestamp":  event.Timestamp.Format(time.RFC3339),
		"event_type": "MCPServerInstanceError",
		"data":       event,
	}

	message := map[string]any{
		"data":    eventData,
		"headers": map[string]any{},
	}

	eventBytes, err := json.Marshal(message)
	if err != nil {
		p.logger.Error("Failed to marshal error event",
			slog.String("instance_id", instanceID),
			slog.String("error", err.Error()))
		return err
	}

	err = p.redisClient.Publish(ctx, "MCPServerInstanceError", string(eventBytes)).Err()
	if err != nil {
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
	p.PublishError(ctx, instanceID, name, errorMsg)
	return p.PublishStatusUpdate(ctx, instanceID, name, "failed", "", "")
}

// Close closes the Redis connection
func (p *EventPublisher) Close() error {
	return p.redisClient.Close()
}

// generateEventID generates a unique event ID
func generateEventID() string {
	return "evt_" + time.Now().Format("20060102_150405") + "_" + randomString(8)
}

// randomString generates a random string of specified length
func randomString(length int) string {
	const charset = "abcdefghijklmnopqrstuvwxyz0123456789"
	b := make([]byte, length)
	for i := range b {
		b[i] = charset[time.Now().UnixNano()%int64(len(charset))]
	}
	return string(b)
}
