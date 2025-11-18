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

// MCPServerInstanceCreated represents the event when an MCP instance is created
type MCPServerInstanceCreated struct {
	InstanceID   string         `json:"instance_id"`
	Name         string         `json:"name"`
	ServerSpecID string         `json:"server_spec_id,omitempty"`
	JSONSpec     map[string]any `json:"json_spec"`
}

// MCPServerInstanceDeleted represents the event when an MCP instance is deleted
type MCPServerInstanceDeleted struct {
	InstanceID string `json:"instance_id"`
	Name       string `json:"name"`
}

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

	// Subscribe to MCP events
	pubsub := s.redisClient.Subscribe(ctx, "MCPServerInstanceCreated", "MCPServerInstanceDeleted")
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
	case "MCPServerInstanceCreated":
		s.handleInstanceCreated(ctx, msg.Payload)
	case "MCPServerInstanceDeleted":
		s.handleInstanceDeleted(ctx, msg.Payload)
	default:
		s.logger.Warn("Unknown event channel", slog.String("channel", msg.Channel))
	}
}

// EventMessage represents the wrapper structure from FastStream Redis
type EventMessage struct {
	Data    string         `json:"data"`
	Headers map[string]any `json:"headers"`
}

// EventData represents the inner event data structure
type EventData struct {
	EventID   string         `json:"event_id"`
	Timestamp string         `json:"timestamp"`
	EventType string         `json:"event_type"`
	Data      map[string]any `json:"data"`
}

// handleInstanceCreated processes MCP instance creation events
func (s *EventSubscriber) handleInstanceCreated(ctx context.Context, payload string) {
	s.logger.Info("Raw payload received", slog.String("payload", payload))

	// First unmarshal the outer FastStream message structure
	var message EventMessage
	if err := json.Unmarshal([]byte(payload), &message); err != nil {
		s.logger.Error("Failed to unmarshal event message",
			slog.String("error", err.Error()),
			slog.String("payload", payload))
		return
	}

	s.logger.Info("Outer message parsed",
		slog.String("data", message.Data),
		slog.Any("headers", message.Headers))

	// Then unmarshal the inner event data (message.Data is a JSON string)
	var eventData EventData
	if err := json.Unmarshal([]byte(message.Data), &eventData); err != nil {
		s.logger.Error("Failed to unmarshal event data",
			slog.String("error", err.Error()),
			slog.String("data", message.Data))
		return
	}

	s.logger.Info("Parsed event data structure",
		slog.String("event_id", eventData.EventID),
		slog.String("event_type", eventData.EventType),
		slog.Any("data_keys", getMapKeys(eventData.Data)),
		slog.Any("full_data", eventData.Data))

	// Extract the actual event fields from the data
	instanceID, instanceOK := eventData.Data["instance_id"].(string)
	name, nameOK := eventData.Data["name"].(string)
	serverSpecID, serverSpecOK := eventData.Data["server_spec_id"].(string)
	jsonSpecInterface, jsonSpecOK := eventData.Data["json_spec"]

	var jsonSpec map[string]any
	if jsonSpecInterface != nil {
		jsonSpec, _ = jsonSpecInterface.(map[string]any)
	}

	s.logger.Info("Extracted event data",
		slog.String("instance_id", instanceID),
		slog.Bool("instance_id_ok", instanceOK),
		slog.String("name", name),
		slog.Bool("name_ok", nameOK),
		slog.String("server_spec_id", serverSpecID),
		slog.Bool("server_spec_id_ok", serverSpecOK),
		slog.Any("json_spec_raw", jsonSpecInterface),
		slog.Bool("json_spec_ok", jsonSpecOK),
		slog.Any("json_spec_parsed", jsonSpec))

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

// handleInstanceDeleted processes MCP instance deletion events
func (s *EventSubscriber) handleInstanceDeleted(ctx context.Context, payload string) {
	// First unmarshal the outer FastStream message structure
	var message EventMessage
	if err := json.Unmarshal([]byte(payload), &message); err != nil {
		s.logger.Error("Failed to unmarshal event message",
			slog.String("error", err.Error()),
			slog.String("payload", payload))
		return
	}

	// Then unmarshal the inner event data
	var eventData EventData
	if err := json.Unmarshal([]byte(message.Data), &eventData); err != nil {
		s.logger.Error("Failed to unmarshal event data",
			slog.String("error", err.Error()),
			slog.String("data", message.Data))
		return
	}

	// Extract the actual event fields from the data
	instanceID, _ := eventData.Data["instance_id"].(string)

	s.logger.Info("Processing MCP instance deletion",
		slog.String("instance_id", instanceID))

	// Extract name from event data for deletion
	name, _ := eventData.Data["name"].(string)

	// For deletion, we need to determine which provider to use
	// Since we don't have the full instance data, we'll try both providers
	// In a production system, you might want to store provider type in a registry

	// Try Docker provider first
	dockerProvider, _ := s.providerManager.GetProvider(&models.MCPServerInstance{
		JSONSpec: map[string]any{"type": "docker"},
	})
	if err := dockerProvider.DeleteInstance(ctx, instanceID, name); err != nil {
		s.logger.Debug("Docker provider deletion failed (may not be docker type)",
			slog.String("instance_id", instanceID),
			slog.String("error", err.Error()))
	}

	// Try URL provider
	urlProvider, _ := s.providerManager.GetProvider(&models.MCPServerInstance{
		JSONSpec: map[string]any{"type": "url"},
	})
	if err := urlProvider.DeleteInstance(ctx, instanceID, name); err != nil {
		s.logger.Debug("URL provider deletion failed (may not be URL type)",
			slog.String("instance_id", instanceID),
			slog.String("error", err.Error()))
	}

	s.logger.Info("Processed MCP instance deletion",
		slog.String("instance_id", instanceID))
}

// Close closes the Redis connection
func (s *EventSubscriber) Close() error {
	return s.redisClient.Close()
}

// Helper function to get map keys for debugging
func getMapKeys(m map[string]any) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	return keys
}
