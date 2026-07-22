package events

import (
	"context"
	"log/slog"
	"strings"

	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/agentarea/mcp-manager/internal/providers"
	redis "github.com/go-redis/redis/v8"
)

// EventSubscriber handles Redis event subscriptions for MCP events
type EventSubscriber struct {
	redisClient     *redis.Client
	providerManager *providers.ProviderManager
	logger          *slog.Logger
}

// NewEventSubscriber creates a new event subscriber
func NewEventSubscriber(redisURL string, providerManager *providers.ProviderManager, logger *slog.Logger) *EventSubscriber {
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

	return &EventSubscriber{
		redisClient:     rdb,
		providerManager: providerManager,
		logger:          logger,
	}
}

// Start begins listening for events
func (s *EventSubscriber) Start(ctx context.Context) error {
	s.logger.Info("Starting event subscriber")

	pubsub := s.redisClient.Subscribe(ctx,
		"agentarea.events.mcp.instance.created",
		"agentarea.events.mcp.instance.deleted",
	)
	defer pubsub.Close()

	// Test Redis connection
	_, err := s.redisClient.Ping(ctx).Result()
	if err != nil {
		s.logger.Error("Failed to connect to Redis", slog.String("error", err.Error()))
		return err
	}

	s.logger.Info("Connected to Redis, listening for events")

	// Listen for messages
	ch := pubsub.Channel()
	for {
		select {
		case <-ctx.Done():
			s.logger.Info("Event subscriber shutting down")
			return ctx.Err()
		case msg := <-ch:
			if msg == nil {
				continue
			}
			s.handleMessage(ctx, msg)
		}
	}
}

// handleMessage processes incoming Redis messages
func (s *EventSubscriber) handleMessage(ctx context.Context, msg *redis.Message) {
	s.logger.Info("Received event",
		slog.String("channel", msg.Channel),
		slog.String("payload", msg.Payload))

	switch msg.Channel {
	case "agentarea.events.mcp.instance.created":
		s.handleInstanceCreated(msg.Payload)
	case "agentarea.events.mcp.instance.deleted":
		s.handleInstanceDeleted(ctx, msg.Payload)
	default:
		s.logger.Warn("Unknown event channel", slog.String("channel", msg.Channel))
	}
}

// handleInstanceCreated ignores the event: Python verify() calls POST /instances
// synchronously and owns provisioning, so acting on this event races the HTTP path
// and leaves orphan configmaps/secrets.
func (s *EventSubscriber) handleInstanceCreated(payload string) {
	s.logger.Debug("Ignoring InstanceCreated event (provisioning is owned by Python verify())",
		slog.String("payload", payload))
}

// handleInstanceDeleted parses the shared event format and deletes the instance
// from every provider that might hold it.
func (s *EventSubscriber) handleInstanceDeleted(ctx context.Context, payload string) {
	event, err := ParseSharedEvent(payload)
	if err != nil {
		s.logger.Error("Failed to parse InstanceDeleted event",
			slog.String("error", err.Error()),
			slog.String("payload", payload))
		return
	}

	instanceID, ok := event.GetDataString("instance_id")
	if !ok || instanceID == "" {
		s.logger.Error("InstanceDeleted event is missing instance_id",
			slog.String("payload", payload))
		return
	}

	name, _ := event.GetDataString("name")

	s.logger.Info("Processing MCP instance deletion",
		slog.String("instance_id", instanceID))

	// Try Docker provider
	dockerProvider, _ := s.providerManager.GetProvider(&models.MCPServerInstance{
		JSONSpec: map[string]any{"type": "docker"},
	})
	if err := dockerProvider.DeleteInstance(ctx, instanceID, name); err != nil {
		s.logger.Debug("Docker provider deletion failed",
			slog.String("instance_id", instanceID))
	}

	// Try URL provider
	urlProvider, _ := s.providerManager.GetProvider(&models.MCPServerInstance{
		JSONSpec: map[string]any{"type": "url"},
	})
	if err := urlProvider.DeleteInstance(ctx, instanceID, name); err != nil {
		s.logger.Debug("URL provider deletion failed",
			slog.String("instance_id", instanceID))
	}

	s.logger.Info("Processed MCP instance deletion",
		slog.String("instance_id", instanceID))
}

// Close closes the Redis connection
func (s *EventSubscriber) Close() error {
	return s.redisClient.Close()
}
