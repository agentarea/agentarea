package domain

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"regexp"
	"strings"
)

// The decision question an LLM condition asks a decision model, and its two options.
const (
	ConditionQuestion = "condition_met"
	ConditionMet      = "true"
	ConditionNotMet   = "false"
	// ConditionMaxTokens is _CONDITION_MAX_TOKENS: the most a condition or extraction answer may run to.
	ConditionMaxTokens = 1000
)

// LLMQuestion is one LLM condition asked about one event.
type LLMQuestion struct {
	ModelID     string
	Description string
	Event       map[string]any
	// Context is the condition's context_fields read from the event; nil when it names none.
	Context  map[string]any
	Examples []any
}

// LLMJudge answers an LLM condition with the model it names. Its errors that are not
// ConditionFailed are reported as "Condition evaluation failed: …".
type LLMJudge func(ctx context.Context, q LLMQuestion) (ConditionVerdict, error)

// ConditionFailed is LLMConditionEvaluationError raised by a judge: reported in its own words.
func ConditionFailed(msg string) error { return &conditionError{msg} }

// TriggerContext is the trigger_context an LLM call is given about the trigger it decides for.
func TriggerContext(t Trigger) map[string]any {
	return map[string]any{"trigger_id": t.ID, "trigger_name": t.Name, "trigger_type": t.Type, "agent_id": t.AgentID}
}

func indented(v any) string {
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	enc.SetIndent("", "  ")
	if err := enc.Encode(v); err != nil {
		return fmt.Sprint(v)
	}
	return strings.TrimRight(b.String(), "\n")
}

// ConditionPrompt is _build_evaluation_prompt.
func ConditionPrompt(q LLMQuestion, trigger map[string]any) string {
	parts := []string{
		"You are an AI assistant that evaluates trigger conditions based on event data.", "",
		"CONDITION TO EVALUATE: " + q.Description, "",
		"EVENT DATA:", indented(q.Event), "",
	}
	if len(q.Context) > 0 {
		parts = append(parts, "RELEVANT CONTEXT:", indented(q.Context), "")
	}
	if len(trigger) > 0 {
		parts = append(parts, "TRIGGER CONTEXT:", indented(trigger), "")
	}
	if len(q.Examples) > 0 {
		parts = append(parts, "EXAMPLES:")
		for i, ex := range q.Examples {
			m, _ := ex.(map[string]any)
			input, ok := m["input"]
			if !ok {
				input = map[string]any{}
			}
			parts = append(parts, fmt.Sprintf("Example %d:", i+1), "Input: "+indented(input), "Expected: "+pyStr(m["expected"]), "")
		}
	}
	parts = append(parts,
		"Decide whether the event meets the condition.",
		`Reply with one JSON object and nothing else: {"verdict": "met" or "not_met", "score": a number from 0 to 1 for how sure you are, "reason": one short sentence}.`,
	)
	return strings.Join(parts, "\n")
}

// ConditionDecision is _decide_condition's state and question for a decision model.
func ConditionDecision(q LLMQuestion, trigger map[string]any) (map[string]any, map[string]any) {
	state := map[string]any{"event": q.Event}
	if len(q.Context) > 0 {
		state["relevant_context"] = q.Context
	}
	if len(trigger) > 0 {
		state["trigger_context"] = trigger
	}
	if len(q.Examples) > 0 {
		state["examples"] = q.Examples
	}
	questions := map[string]any{ConditionQuestion: map[string]any{
		"type":         "choice",
		"instructions": "Is this condition met by the event: " + q.Description,
		"criteria": map[string]any{
			ConditionMet:    "The event meets the condition",
			ConditionNotMet: "The event does not meet the condition",
		},
	}}
	return state, questions
}

// DecisionVerdict is the verdict a decision model's choice gives.
func DecisionVerdict(modelID string, answers map[string]map[string]any) (ConditionVerdict, error) {
	choice := answers[ConditionQuestion]["choice"]
	switch choice {
	case ConditionMet, ConditionNotMet:
		return ConditionVerdict{Met: choice == ConditionMet, Reason: fmt.Sprintf("decision model %s chose %s", modelID, choice)}, nil
	}
	return ConditionVerdict{}, ConditionFailed(fmt.Sprintf("Decision model answered %s", pyReprValue(choice)))
}

var fence = regexp.MustCompile("(?s)^```(?:json)?\\s*(.*?)\\s*```$")

// ParseVerdict is _parse_verdict: the model's JSON verdict; prose is not a verdict.
func ParseVerdict(response string) (ConditionVerdict, error) {
	text := strings.TrimSpace(response)
	if m := fence.FindStringSubmatch(text); m != nil {
		text = m[1]
	}
	var payload any
	dec := json.NewDecoder(strings.NewReader(text))
	if err := dec.Decode(&payload); err != nil || dec.More() {
		head := response
		if r := []rune(head); len(r) > 200 {
			head = string(r[:200])
		}
		return ConditionVerdict{}, ConditionFailed("Condition model did not answer in JSON: " + pyReprValue(head))
	}
	invalid := func(why string) (ConditionVerdict, error) {
		return ConditionVerdict{}, ConditionFailed("Condition model gave no valid verdict: " + why)
	}
	m, ok := payload.(map[string]any)
	if !ok {
		return invalid("the answer is not an object")
	}
	verdict, _ := m["verdict"].(string)
	if verdict != "met" && verdict != "not_met" {
		return invalid("verdict must be 'met' or 'not_met'")
	}
	reason, _ := m["reason"].(string)
	if reason == "" {
		return invalid("reason must be a non-empty string")
	}
	v := ConditionVerdict{Met: verdict == "met", Reason: reason}
	if raw, present := m["score"]; present && raw != nil {
		score, ok := raw.(float64)
		if !ok || score < 0 || score > 1 {
			return invalid("score must be a number from 0 to 1")
		}
		v.Score = &score
	}
	return v, nil
}

// ExtractionPrompt is _build_parameter_extraction_prompt.
func ExtractionPrompt(instruction string, event, trigger map[string]any) string {
	parts := []string{
		"You are an AI assistant that extracts task parameters from event data.", "",
		"INSTRUCTION: " + instruction, "",
		"EVENT DATA:", indented(event), "",
	}
	if len(trigger) > 0 {
		parts = append(parts, "TRIGGER CONTEXT:", indented(trigger), "")
	}
	parts = append(parts,
		"Based on the instruction and event data, extract relevant parameters for task execution.",
		"Return your response as a valid JSON object containing the extracted parameters.",
		"Include any relevant data from the event that would be useful for the task.",
		"Example response format:",
		"{",
		`  "user_id": "extracted_user_id",`,
		`  "message": "extracted_message_content",`,
		`  "file_url": "extracted_file_url",`,
		`  "additional_context": "any_other_relevant_data"`,
		"}",
	)
	return strings.Join(parts, "\n")
}

// ExtractedParameters is extract_task_parameters' reading of the answer: a JSON object, else the
// event, the instruction and the raw answer.
func ExtractedParameters(response, instruction string, event map[string]any) (map[string]any, bool) {
	var out map[string]any
	if err := json.Unmarshal([]byte(strings.TrimSpace(response)), &out); err == nil && out != nil {
		return out, true
	}
	return map[string]any{"event_data": event, "instruction": instruction, "llm_response": response}, false
}
