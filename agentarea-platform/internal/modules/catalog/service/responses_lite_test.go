package service

import (
	"encoding/json"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/domain"
)

func TestAModelEntryCarriesItsResponsesLiteFlag(t *testing.T) {
	entries, err := parseModels(map[string]any{"models": []any{
		map[string]any{"provider_key": "openai_codex", "model_name": "gpt-6.2-sol", "context_window": json.Number("500000"),
			"input_cost_per_token": json.Number("0"), "output_cost_per_token": json.Number("0"), "responses_lite": true},
		map[string]any{"provider_key": "openai_codex", "model_name": "gpt-5.5", "context_window": json.Number("272000"),
			"input_cost_per_token": json.Number("0"), "output_cost_per_token": json.Number("0")},
	}})
	if err != nil || len(entries) != 2 {
		t.Fatalf("parse: %v %v", entries, err)
	}
	lite, err := modelRow(domain.Item{Name: "GPT-6.2 Sol"}, entries[0].Spec, [16]byte{})
	if err != nil || !lite.ResponsesLite {
		t.Fatalf("lite row: %+v %v", lite, err)
	}
	plain, err := modelRow(domain.Item{Name: "GPT-5.5"}, entries[1].Spec, [16]byte{})
	if err != nil || plain.ResponsesLite {
		t.Fatalf("plain row: %+v %v", plain, err)
	}
	bad := entries[0].Spec
	bad["responses_lite"] = "yes"
	if _, err := modelRow(domain.Item{}, bad, [16]byte{}); err == nil {
		t.Fatal("a non-bool responses_lite was accepted")
	}
}
