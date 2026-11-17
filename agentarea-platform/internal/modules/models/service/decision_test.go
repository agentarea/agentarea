package service

import (
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
)

func TestADecisionAnswersEveryQuestionAndItsCostFollowsTheReportOrTheSpec(t *testing.T) {
	questions := map[string]any{"met": map[string]any{"type": "choice", "instructions": "x", "criteria": map[string]any{"true": "y"}}}
	if err := validateQuestions(questions); err != nil {
		t.Fatal(err)
	}
	if err := validateQuestions(map[string]any{"s": map[string]any{"type": "score", "instructions": "x"}}); err == nil ||
		err.Error() != "score question 's' needs a non-empty criteria list" {
		t.Fatalf("score without criteria = %v", err)
	}
	reported, err := decisionReply(api.ResolvedModel{}, questions, []byte(`{"answers": {"met": {"type": "choice", "choice": "true"}}, "usage": {"input_tokens": 10, "output_tokens": 2, "cost": 0.05}}`))
	if err != nil || reported.Answers["met"]["choice"] != "true" || !reported.CostUSD.Equal(money.MustParse("0.05")) {
		t.Fatalf("reported %+v %v", reported, err)
	}
	price := money.MustParse("0.01")
	priced, err := decisionReply(api.ResolvedModel{Prices: api.ModelPrices{Input: &price, Output: &price}}, questions,
		[]byte(`{"answers": {"met": {"type": "choice", "choice": "false"}}, "usage": {"input_tokens": 10, "output_tokens": 2}}`))
	if err != nil || !priced.CostUSD.Equal(money.MustParse("0.12")) {
		t.Fatalf("priced %+v %v", priced, err)
	}
	unknown, err := decisionReply(api.ResolvedModel{}, questions, []byte(`{"answers": {"met": {"type": "choice", "choice": "false"}}, "usage": {"input_tokens": 1, "output_tokens": 1}}`))
	if err != nil || unknown.CostUSD != nil {
		t.Fatalf("unknown %+v %v", unknown, err)
	}
	if _, err := decisionReply(api.ResolvedModel{}, questions, []byte(`{"answers": {"met": {"type": "score", "score": 1}}, "usage": {"input_tokens": 1, "output_tokens": 1}}`)); err == nil ||
		err.Error() != "decision returned no choice answer for question 'met'" {
		t.Fatalf("wrong answer type = %v", err)
	}
}
