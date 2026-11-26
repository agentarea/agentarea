package operator

import (
	"strings"
	"testing"
)

func TestExplicitModelTakesItsKind(t *testing.T) {
	m, _, err := explicitModel(map[string]any{"modelName": "gemini-decision-1", "kind": "decision"})
	if err != nil || m.Kind != "decision" {
		t.Fatalf("kind = %q, err = %v", m.Kind, err)
	}
	m, _, err = explicitModel(map[string]any{"modelName": "gemini-3.8-flash"})
	if err != nil || m.Kind != "" {
		t.Fatalf("an entry without a kind: %q, %v", m.Kind, err)
	}
	if _, _, err := explicitModel(map[string]any{"modelName": "x", "kind": "embedding"}); err == nil || !strings.Contains(err.Error(), "kind of x") {
		t.Fatalf("an undeclarable kind: %v", err)
	}
}
