package domain

import (
	"encoding/json"
	"fmt"
	"strings"
)

// A2UIDelimiter separates a reply's text from its A2UI JSON.
const A2UIDelimiter = "---a2ui_JSON---"

const (
	a2uiMaxJSONSize = 100 * 1024
	a2uiMaxEvents   = 50
)

// A2UICanonical maps an A2UI event type to its task event type.
func A2UICanonical(t string) (string, bool) {
	switch t {
	case "A2UICreateSurface":
		return EventA2UICreate, true
	case "A2UIUpdateComponents":
		return EventA2UIUpdateComponents, true
	case "A2UIUpdateDataModel":
		return EventA2UIUpdateData, true
	case "A2UIDeleteSurface":
		return EventA2UIDelete, true
	}
	return "", false
}

// A2UIParseResult is a reply split into text and validated A2UI events.
type A2UIParseResult struct {
	Text       string
	Events     []map[string]any
	ParseError string
}

// ParseA2UI is parse_a2ui_response.
func ParseA2UI(content string) A2UIParseResult {
	text, jsonPart, found := strings.Cut(content, A2UIDelimiter)
	if !found {
		return A2UIParseResult{Text: content}
	}
	text = strings.TrimRight(text, " \t\r\n\v\f")
	jsonPart = strings.TrimSpace(jsonPart)
	if jsonPart == "" {
		return A2UIParseResult{Text: text, ParseError: "Empty A2UI JSON after delimiter"}
	}
	if len(jsonPart) > a2uiMaxJSONSize {
		return A2UIParseResult{Text: text, ParseError: fmt.Sprintf("A2UI JSON exceeds %d byte limit", a2uiMaxJSONSize)}
	}
	var parsed any
	if err := json.Unmarshal([]byte(jsonPart), &parsed); err != nil {
		return A2UIParseResult{Text: text, ParseError: "Invalid JSON: " + err.Error()}
	}
	obj, ok := parsed.(map[string]any)
	if !ok {
		return A2UIParseResult{Text: text, ParseError: "A2UI payload must be a JSON object"}
	}
	rawEvents, has := obj["events"]
	if !has {
		rawEvents = []any{}
	}
	events, ok := rawEvents.([]any)
	if !ok {
		return A2UIParseResult{Text: text, ParseError: "'events' must be a list"}
	}
	if len(events) > a2uiMaxEvents {
		events = events[:a2uiMaxEvents]
	}
	var valid []map[string]any
	for _, e := range events {
		ev, isMap := e.(map[string]any)
		if !isMap {
			continue
		}
		t, _ := ev["type"].(string)
		if _, known := A2UICanonical(t); !known || !truthy(ev["surface_id"]) {
			continue
		}
		valid = append(valid, ev)
	}
	return A2UIParseResult{Text: text, Events: valid}
}
