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

// handleInstanceCreated processes MCP instance creation events (shared format)
func (s *EventSubscriber) handleInstanceCreated(ctx context.Context, payload string) {
	s.logger.Info("Parsing shared format event", slog.String("payload", payload))

	// Parse using shared framework-independent format
	event, err := ParseSharedEvent(payload)
	if err != nil {
		s.logger.Error("Failed to parse shared event",
			slog.String("error", err.Error()),
			slog.String("payload", payload))
		return
	}

	s.logger.Info("Parsed shared event",
		slog.String("event_id", event.ID),
		slog.String("event_type", event.Type),
		slog.String("correlation_id", event.CorrelationID))

	// Extract data from the shared format
	instanceID, _ := event.GetDataString("instance_id")
	name, _ := event.GetDataString("name")
	serverSpecID, _ := event.GetDataString("server_spec_id")
	jsonSpec, _ := event.GetDataMap("json_spec")

	if instanceID == "" {
		s.logger.Error("Missing instance_id in event data")
		return
	}

	s.logger.Info("Processing MCP instance creation",
		slog.String("instance_id", instanceID),
		slog.String("name", name),
		slog.Any("json_spec", jsonSpec))

	// Create MCP server instance model
	instance := &models.MCPServerInstance{
		InstanceID:   instanceID,
		Name:         name,
		ServerSpecID: serverSpecID,
		JSONSpec:     jsonSpec,
		Status:       "pending",
	}

	// Get the appropriate provider and create the instance
	provider, err := s.providerManager.GetProvider(instance)
	if err != nil {
		s.logger.Error("Failed to get provider",
			slog.String("instance_id", instanceID),
			slog.String("error", err.Error()))
		return
	}

	if err := provider.CreateInstance(ctx, instance); err != nil {
		s.logger.Error("Failed to create MCP instance",
			slog.String("instance_id", instanceID),
			slog.String("error", err.Error()))
	} else {
		s.logger.Info("Successfully created MCP instance",
			slog.String("instance_id", instanceID))
	}
}

// handleInstanceDeleted processes MCP instance deletion events (shared format)
func (s *EventSubscriber) handleInstanceDeleted(ctx context.Context, payload string) {
	event, err := ParseSharedEvent(payload)
	if err != nil {
		s.logger.Error("Failed to parse shared event",
			slog.String("error", err.Error()))
		return
	}

	instanceID, _ := event.GetDataString("instance_id")
	name, _ := event.GetDataString("name")

	s.logger.Info("Processing MCP instance deletion",
		slog.String("instance_id", instanceID))

	// Try Kubernetes provider first
	kubernetesProvider, _ := s.providerManager.GetProvider(&models.MCPServerInstance{
		JSONSpec: map[string]any{"type": "kubernetes"},
	})
	if err := kubernetesProvider.DeleteInstance(ctx, instanceID, name); err != nil {
		s.logger.Debug("Kubernetes provider deletion failed",
			slog.String("instance_id", instanceID),
			slog.String("error", err.Error()))
	}

	// Try Docker provider
	dockerProvider, _ := s.providerManager.GetProvider(&models.MCPServerInstance{
		JSONSpec: map[string]any{"type": "docker"},
	})
	if err := dockerProvider.DeleteInstance(ctx, instanceID, name); err != nil {
		s.logger.Debug("Docker provider deletion failed",
			slog.String("instance_id", instanceID),
			slog.String("error", err.Error()))
	}

	// Try URL provider
	urlProvider, _ := s.providerManager.GetProvider(&models.MCPServerInstance{
		JSONSpec: map[string]any{"type": "url"},
	})
	if err := urlProvider.DeleteInstance(ctx, instanceID, name); err != nil {
		s.logger.Debug("URL provider deletion failed",
			slog.String("instance_id", instanceID),
			slog.String("error", err.Error()))
	}

	s.logger.Info("Processed MCP instance deletion",
		slog.String("instance_id", instanceID))
}

// tryHandleInstanceCreated attempts to parse and handle instance creation using shared format.
// Returns true if successful, false if parsing failed (caller should try legacy format).
func (s *EventSubscriber) tryHandleInstanceCreated(ctx context.Context, payload string) bool {
	// Try to parse as shared format
	event, err := ParseSharedEvent(payload)
	if err != nil {
		s.logger.Debug("Failed to parse as shared format, will try legacy",
			slog.String("error", err.Error()))
		return false
	}

	// Validate required fields
	instanceID, ok := event.GetDataString("instance_id")
	if !ok || instanceID == "" {
		s.logger.Debug("Missing instance_id in shared format, will try legacy")
		return false
	}

	s.logger.Info("Successfully parsed shared format event",
		slog.String("event_id", event.ID),
		slog.String("event_type", event.Type))

	// Extract data
	name, _ := event.GetDataString("name")
	serverSpecID, _ := event.GetDataString("server_spec_id")
	jsonSpec, _ := event.GetDataMap("json_spec")

	// Create instance
	instance := &models.MCPServerInstance{
		InstanceID:   instanceID,
		Name:         name,
		ServerSpecID: serverSpecID,
		JSONSpec:     jsonSpec,
		Status:       "pending",
	}

	provider, err := s.providerManager.GetProvider(instance)
	if err != nil {
		s.logger.Error("Failed to get provider",
			slog.String("instance_id", instanceID),
			slog.String("error", err.Error()))
		return true // Parsed successfully, but failed to process
	}

	if err := provider.CreateInstance(ctx, instance); err != nil {
		s.logger.Error("Failed to create MCP instance",
			slog.String("instance_id", instanceID),
			slog.String("error", err.Error()))
	} else {
		s.logger.Info("Successfully created MCP instance",
			slog.String("instance_id", instanceID))
	}

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

// handleLegacyInstanceCreated handles old format events
func (s *EventSubscriber) handleLegacyInstanceCreated(ctx context.Context, payload string) {
	s.logger.Info("Handling legacy format event", slog.String("payload", payload))

	// Try to parse as legacy FastStream format
	var message LegacyEventMessage
	if err := json.Unmarshal([]byte(payload), &message); err != nil {
		s.logger.Error("Failed to parse legacy event",
			slog.String("error", err.Error()))
		return
	}

	var eventData LegacyEventData
	if err := json.Unmarshal([]byte(message.Data), &eventData); err != nil {
		s.logger.Error("Failed to parse legacy event data",
			slog.String("error", err.Error()))
		return
	}

	// Extract fields
	instanceID, _ := eventData.Data["instance_id"].(string)
	name, _ := eventData.Data["name"].(string)
	serverSpecID, _ := eventData.Data["server_spec_id"].(string)
	jsonSpec, _ := eventData.Data["json_spec"].(map[string]any)

	s.logger.Info("Processing legacy MCP instance creation",
		slog.String("instance_id", instanceID))

	instance := &models.MCPServerInstance{
		InstanceID:   instanceID,
		Name:         name,
		ServerSpecID: serverSpecID,
		JSONSpec:     jsonSpec,
		Status:       "pending",
	}

	provider, err := s.providerManager.GetProvider(instance)
	if err != nil {
		s.logger.Error("Failed to get provider",
			slog.String("error", err.Error()))
		return
	}

	if err := provider.CreateInstance(ctx, instance); err != nil {
		s.logger.Error("Failed to create MCP instance",
			slog.String("error", err.Error()))
	}
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
	dockerProvider.DeleteInstance(ctx, instanceID, name)

	urlProvider, _ := s.providerManager.GetProvider(&models.MCPServerInstance{
		JSONSpec: map[string]any{"type": "url"},
	})
	urlProvider.DeleteInstance(ctx, instanceID, name)
}

// Close closes the Redis connection
func (s *EventSubscriber) Close() error {
	return s.redisClient.Close()
}
