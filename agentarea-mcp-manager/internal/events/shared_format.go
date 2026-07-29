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
