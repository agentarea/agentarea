package events

import (
	"encoding/json"
	"time"
)

// SharedEvent represents the framework-independent event format.
// Based on CloudEvents specification for cross-language compatibility.
type SharedEvent struct {
	SpecVersion     string                 `json:"specversion"`
	Type            string                 `json:"type"`
	Source          string                 `json:"source"`
	ID              string                 `json:"id"`
	Time            time.Time              `json:"time"`
	DataContentType string                 `json:"datacontenttype,omitempty"`
	CorrelationID   string                 `json:"correlationid,omitempty"`
	Data            map[string]interface{} `json:"data"`
}

// ParseSharedEvent parses a JSON payload into SharedEvent.
// This is the framework-independent format used by Python and Go services.
func ParseSharedEvent(payload string) (*SharedEvent, error) {
	var event SharedEvent
	if err := json.Unmarshal([]byte(payload), &event); err != nil {
		return nil, err
	}
	return &event, nil
}

// GetDataString extracts a string value from the event data.
func (e *SharedEvent) GetDataString(key string) (string, bool) {
	val, ok := e.Data[key]
	if !ok {
		return "", false
	}
	str, ok := val.(string)
	return str, ok
}

// GetDataMap extracts a map value from the event data.
func (e *SharedEvent) GetDataMap(key string) (map[string]interface{}, bool) {
	val, ok := e.Data[key]
	if !ok {
		return nil, false
	}
	m, ok := val.(map[string]interface{})
	return m, ok
}

// Event types for MCP
const (
	EventTypeMCPInstanceCreated = "com.agentarea.mcp.instance.created"
	EventTypeMCPInstanceDeleted = "com.agentarea.mcp.instance.deleted"
	EventTypeMCPInstanceStarted = "com.agentarea.mcp.instance.started"
	EventTypeMCPInstanceStopped = "com.agentarea.mcp.instance.stopped"
	EventTypeMCPInstanceFailed  = "com.agentarea.mcp.instance.failed"
)

// GetChannelForEventType returns the Redis channel name for an event type.
// Pattern: agentarea.events.{domain}.{action}
func GetChannelForEventType(eventType string) string {
	// Convert reverse DNS to channel path
	// com.agentarea.mcp.instance.created -> agentarea.events.mcp.instance.created
	// For backward compatibility, also handle legacy format
	switch eventType {
	case EventTypeMCPInstanceCreated:
		return "agentarea.events.mcp.instance.created"
	case EventTypeMCPInstanceDeleted:
		return "agentarea.events.mcp.instance.deleted"
	default:
		return "agentarea.events." + eventType
	}
}
