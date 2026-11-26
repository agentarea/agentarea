package domain

import (
	"testing"
	"time"
)

func TestAChargeWithoutSettlementDoesNotWaitOnOne(t *testing.T) {
	task := "0b6e7d5c-1d2a-4c3b-9e8f-7a6b5c4d3e2f"
	for _, e := range []StoredEvent{
		{ID: "e1", Type: EventLLMCompleted, Timestamp: time.Unix(0, 0), Data: map[string]any{
			"task_id": task, "model_id": "m",
			"usage": map[string]any{"usage": map[string]any{"prompt_tokens": 1, "billing": map[string]any{
				"amount": "0.5", "currency": "USD", "settle": "", "hold_id": "",
			}}},
		}},
		{ID: "e2", Type: EventToolResult, Timestamp: time.Unix(0, 0), Data: map[string]any{
			"task_id": task, "tool_name": "t", "model_billing": map[string]any{"amount": "0.5", "settle": "", "hold_id": ""},
		}},
	} {
		lines := CostLines(e, "USD")
		if len(lines) == 0 {
			t.Fatalf("%s: no line", e.Type)
		}
		for _, l := range lines {
			for _, k := range []string{"settle", "hold_id"} {
				if _, ok := l.Evidence[k]; ok {
					t.Fatalf("%s: evidence %v keeps an empty %s", e.Type, l.Evidence, k)
				}
			}
		}
	}
}

func TestAModelLineAToolWritesKeepsItsModelInEvidence(t *testing.T) {
	lines := CostLines(StoredEvent{ID: "e1", Type: EventToolResult, Timestamp: time.Unix(0, 0), Data: map[string]any{
		"task_id": "0b6e7d5c-1d2a-4c3b-9e8f-7a6b5c4d3e2f", "tool_name": "llm_call",
		"model_billing": map[string]any{"amount": "0.5", "model_instance_id": "i1", "model": "gemini-4-argon"},
	}}, "USD")
	if len(lines) != 1 || *lines[0].SubjectName != "llm_call" || *lines[0].SubjectID != "i1" || lines[0].Evidence["model"] != "gemini-4-argon" {
		t.Fatalf("lines %+v", lines)
	}
}
