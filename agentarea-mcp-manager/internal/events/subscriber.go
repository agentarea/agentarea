package events

import (
	"context"
	"encoding/json"
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

	// Subscribe to MCP events using new shared format channels
	// Also subscribe to legacy channels for backward compatibility
	pubsub := s.redisClient.Subscribe(ctx,
		"agentarea.events.mcp.instance.created",
		"agentarea.events.mcp.instance.deleted",
		// Legacy channels for backward compatibility
		"MCPServerInstanceCreated",
		"MCPServerInstanceDeleted",
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

	// Check if this is a legacy channel
	// Try shared format first (new events from Python use this format)
	// If that fails, fall back to legacy format
	switch msg.Channel {
	case "MCPServerInstanceCreated", "agentarea.events.mcp.instance.created":
		// Try shared format first
		if s.tryHandleInstanceCreated(ctx, msg.Payload) {
			return
		}
		// Fall back to legacy format
		s.handleLegacyInstanceCreated(ctx, msg.Payload)
	case "MCPServerInstanceDeleted", "agentarea.events.mcp.instance.deleted":
		// Try shared format first
		if s.tryHandleInstanceDeleted(ctx, msg.Payload) {
			return
		}
		// Fall back to legacy format
		s.handleLegacyInstanceDeleted(ctx, msg.Payload)
	default:
		s.logger.Warn("Unknown event channel", slog.String("channel", msg.Channel))
	}
}

// tryHandleInstanceCreated attempts to parse and handle instance creation using shared format.
// Returns true if successful, false if parsing failed (caller should try legacy format).
func (s *EventSubscriber) tryHandleInstanceCreated(_ context.Context, payload string) bool {
	// Phase 1: Python verify() calls POST /instances synchronously and owns
	// provisioning. Acting on this event causes a double-create race with the
	// HTTP path, leaving orphan configmaps/secrets. Return true to signal
	// "handled" so the caller skips the legacy path.
	s.logger.Debug("Ignoring tryHandleInstanceCreated event (provisioning is owned by Python verify())",
		slog.String("payload", payload))
	return true
}

// tryHandleInstanceDeleted attempts to parse and handle instance deletion using shared format.
// Returns true if successful, false if parsing failed (caller should try legacy format).
func (s *EventSubscriber) tryHandleInstanceDeleted(ctx context.Context, payload string) bool {
	// Try to parse as shared format
	event, err := ParseSharedEvent(payload)
	if err != nil {
		s.logger.Debug("Failed to parse as shared format, will try legacy",
			slog.String("error", err.Error()))
		return false
	}

	instanceID, ok := event.GetDataString("instance_id")
	if !ok || instanceID == "" {
		s.logger.Debug("Missing instance_id in shared format, will try legacy")
		return false
	}

	name, _ := event.GetDataString("name")

	s.logger.Info("Processing MCP instance deletion (shared format)",
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

	s.logger.Info("Processed MCP instance deletion (shared format)",
		slog.String("instance_id", instanceID))

	return true
}

// Legacy format types for backward compatibility

// LegacyEventMessage represents the old FastStream wrapper
type LegacyEventMessage struct {
	Data    string         `json:"data"`
	Headers map[string]any `json:"headers"`
}

// LegacyEventData represents the old inner event data
type LegacyEventData struct {
	EventID   string         `json:"event_id"`
	Timestamp string         `json:"timestamp"`
	EventType string         `json:"event_type"`
	Data      map[string]any `json:"data"`
}

// handleLegacyInstanceCreated is a no-op — provisioning is owned by Python
// verify() since Phase 1 of the MCP lifecycle refactor.
func (s *EventSubscriber) handleLegacyInstanceCreated(_ context.Context, payload string) {
	s.logger.Debug("Ignoring legacy InstanceCreated event (provisioning is owned by Python verify())",
		slog.String("payload", payload))
}

// handleLegacyInstanceDeleted handles old format deletion events
func (s *EventSubscriber) handleLegacyInstanceDeleted(ctx context.Context, payload string) {
	var message LegacyEventMessage
	if err := json.Unmarshal([]byte(payload), &message); err != nil {
		s.logger.Error("Failed to parse legacy event", slog.String("error", err.Error()))
		return
	}

	var eventData LegacyEventData
	if err := json.Unmarshal([]byte(message.Data), &eventData); err != nil {
		s.logger.Error("Failed to parse legacy event data", slog.String("error", err.Error()))
		return
	}

	instanceID, _ := eventData.Data["instance_id"].(string)
	name, _ := eventData.Data["name"].(string)

	// Try both providers
	dockerProvider, _ := s.providerManager.GetProvider(&models.MCPServerInstance{
		JSONSpec: map[string]any{"type": "docker"},
	})
	_ = dockerProvider.DeleteInstance(ctx, instanceID, name)

	urlProvider, _ := s.providerManager.GetProvider(&models.MCPServerInstance{
		JSONSpec: map[string]any{"type": "url"},
	})
	_ = urlProvider.DeleteInstance(ctx, instanceID, name)
}

// Close closes the Redis connection
func (s *EventSubscriber) Close() error {
	return s.redisClient.Close()
}
