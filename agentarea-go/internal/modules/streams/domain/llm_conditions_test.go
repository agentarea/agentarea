package domain_test

import (
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
)

func TestAChatModelsVerdictIsItsJSONAndNothingElse(t *testing.T) {
	v, err := domain.ParseVerdict("```json\n{\"verdict\": \"met\", \"score\": 0.9, \"reason\": \"urgent\"}\n```")
	if err != nil || !v.Met || *v.Score != 0.9 || v.Reason != "urgent" {
		t.Fatalf("fenced = %+v %v", v, err)
	}
	if _, err := domain.ParseVerdict("Yes, it is met."); err == nil || err.Error() != "Condition model did not answer in JSON: 'Yes, it is met.'" {
		t.Fatalf("prose = %v", err)
	}
	if _, err := domain.ParseVerdict(`{"verdict": "maybe", "reason": "x"}`); err == nil || !strings.HasPrefix(err.Error(), "Condition model gave no valid verdict: ") {
		t.Fatalf("bad verdict = %v", err)
	}
	if _, err := domain.ParseVerdict(`{"verdict": "met", "score": 2, "reason": "x"}`); err == nil {
		t.Fatal("a score above 1 was accepted")
	}
}

func TestADecisionModelAnswersTheConditionAsAChoice(t *testing.T) {
	state, questions := domain.ConditionDecision(domain.LLMQuestion{Description: "urgent", Event: map[string]any{"a": 1}}, map[string]any{"trigger_id": "t1"})
	q := questions[domain.ConditionQuestion].(map[string]any)
	if q["instructions"] != "Is this condition met by the event: urgent" || state["trigger_context"] == nil || state["relevant_context"] != nil {
		t.Fatalf("state %v questions %v", state, questions)
	}
	v, err := domain.DecisionVerdict("m1", map[string]map[string]any{domain.ConditionQuestion: {"type": "choice", "choice": "false"}})
	if err != nil || v.Met || v.Reason != "decision model m1 chose false" {
		t.Fatalf("verdict %+v %v", v, err)
	}
	if _, err := domain.DecisionVerdict("m1", map[string]map[string]any{domain.ConditionQuestion: {"choice": "perhaps"}}); err == nil || err.Error() != "Decision model answered 'perhaps'" {
		t.Fatalf("odd choice = %v", err)
	}
}

func TestExtractedParametersNeverOverrideOrGrantResources(t *testing.T) {
	params := map[string]any{"trigger_id": "t1"}
	for _, k := range []string{"trigger_id", "mcps", "skills", "files"} {
		if domain.ExtractedKeyAllowed(params, k) {
			t.Errorf("%s may be extracted", k)
		}
	}
	if !domain.ExtractedKeyAllowed(params, "user_id") {
		t.Error("user_id may not be extracted")
	}
	got, ok := domain.ExtractedParameters("not json", "pick the user", map[string]any{"a": 1})
	if ok || got["llm_response"] != "not json" || got["instruction"] != "pick the user" {
		t.Fatalf("fallback %v", got)
	}
}
