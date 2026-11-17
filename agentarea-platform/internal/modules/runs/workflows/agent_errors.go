package workflows

import (
	"errors"
	"fmt"
	"strings"

	"go.temporal.io/sdk/temporal"
)

const governanceDeniedReason = "governance_denied"

const billingUnavailable = "Billing is temporarily unavailable. Please try again later."

func entitlementMessage(code string) (string, bool) {
	switch code {
	case "no_credits":
		return "No credits remaining. Top up your balance to continue.", true
	case "credit_limit_reached":
		return "Credit limit reached. Top up your balance to continue.", true
	case "model_unpriced":
		return "This model is not available on your plan. Choose a different model in the agent settings.", true
	case "billing_unavailable", "billing_error", "account_unresolved":
		return billingUnavailable, true
	}
	return "", false
}

// errorDetails decodes an ApplicationError's details as JSON objects.
func errorDetails(err error) []map[string]any {
	a := appErr(err)
	if a == nil || !a.HasDetails() {
		return nil
	}
	var out []map[string]any
	for i := range 4 {
		vals := make([]any, i+1)
		ptrs := make([]any, i+1)
		for j := range vals {
			ptrs[j] = &vals[j]
		}
		if a.Details(ptrs...) != nil {
			break
		}
		out = out[:0]
		for _, v := range vals {
			if m, ok := v.(map[string]any); ok {
				out = append(out, m)
			}
		}
	}
	return out
}

// governanceDenial is a governance gate refusal's failure reason and user message.
func governanceDenial(err error) (string, string, bool) {
	if appErrorType(err) != ErrGovernanceDenied {
		return "", "", false
	}
	verdict := map[string]any{}
	if d := errorDetails(err); len(d) > 0 {
		verdict = d[0]
	}
	meta, _ := verdict["metadata"].(map[string]any)
	code, _ := meta["entitlement_code"].(string)
	if msg, ok := entitlementMessage(code); ok {
		return code, msg, true
	}
	reason := strings.TrimSpace(fmt.Sprint(verdictValue(verdict, "reason")))
	message := "This request was blocked by policy."
	if reason != "" {
		message = "This request was blocked by policy: " + reason + "."
	}
	if code != "" {
		return code, message, true
	}
	return governanceDeniedReason, message, true
}

func verdictValue(m map[string]any, key string) any {
	if v, ok := m[key]; ok && v != nil {
		return v
	}
	return ""
}

func llmFailure(err error) map[string]any {
	for _, d := range errorDetails(err) {
		if f, ok := d["llm_failure"].(map[string]any); ok {
			return f
		}
	}
	return nil
}

func failureCause(err error) string {
	if appErrorType(err) == ErrDependencyUnavailable {
		return "dependency_unavailable"
	}
	s, _ := llmFailure(err)["cause"].(string)
	return s
}

func activityName(err error) string {
	if a, ok := errors.AsType[*temporal.ActivityError](err); ok && a.ActivityType() != nil {
		return a.ActivityType().GetName()
	}
	return ""
}

func causeText(err error) string {
	if a := appErr(err); a != nil {
		return a.Message()
	}
	return err.Error()
}

func userFacingError(err error) string {
	if _, msg, ok := governanceDenial(err); ok {
		return msg
	}
	if m, _ := llmFailure(err)["message"].(string); m != "" {
		return m
	}
	if t := appErrorType(err); t == ErrRunInputExceedsWindow || t == ErrDependencyUnavailable {
		return causeText(err)
	}
	activity := strings.ToLower(activityName(err))
	combined := strings.ToLower(err.Error()) + " " + strings.ToLower(causeText(err)) + " " + activity
	has := func(words ...string) bool {
		for _, w := range words {
			if strings.Contains(combined, w) {
				return true
			}
		}
		return false
	}
	switch {
	case has("model_id") && has("none", "valid string"):
		return "No model is configured for this agent. Please assign a model in agent settings."
	case has("build_agent_config"):
		return "Agent configuration error. Please check the agent settings."
	case has("call_llm"):
		switch {
		case has("auth", "api_key", "unauthorized"):
			return "Authentication failed with the LLM provider. Please check your API key."
		case has("rate_limit", "429"):
			return "Rate limit exceeded. Please try again in a moment."
		case has("timeout"):
			return "The AI model request timed out. Please try again."
		case has("deprecated"):
			return "The configured model has been deprecated by the provider. Please select a different model."
		case has("not found", "notfounderror", "404"):
			return "The configured model was not found. Please check the model name or select a different one."
		}
		return "Failed to get a response from the AI model."
	case has("execute_mcp_tool", "tool_execution"):
		return "A tool execution failed during the task."
	case has("budget"):
		return "Task budget has been exceeded."
	case has("compact_messages"):
		return "Failed to manage conversation context. Please try again."
	case activity != "":
		return "Task failed during " + strings.ReplaceAll(strings.ReplaceAll(activityName(err), "_activity", ""), "_", " ") + ". Please try again."
	}
	return "An unexpected error occurred. Please try again."
}

func userFacingErrorType(err error) string {
	if _, _, ok := governanceDenial(err); ok {
		return "GovernanceDenied"
	}
	switch appErrorType(err) {
	case ErrRunInputExceedsWindow:
		return "ContextWindowExceeded"
	case ErrDependencyUnavailable:
		return ErrDependencyUnavailable
	}
	if t, _ := llmFailure(err)["error_type"].(string); t != "" {
		return t
	}
	combined := strings.ToLower(err.Error() + " " + causeText(err))
	has := func(words ...string) bool {
		for _, w := range words {
			if strings.Contains(combined, w) {
				return true
			}
		}
		return false
	}
	switch {
	case has("auth", "api_key", "unauthorized"):
		return "AuthenticationError"
	case has("rate_limit", "429"):
		return "RateLimitError"
	case has("deprecated"):
		return "ModelDeprecated"
	case has("not found", "notfounderror", "404"):
		return "ModelNotFound"
	case has("timeout"):
		return "TimeoutError"
	case has("budget", "quota"):
		return "BudgetExceeded"
	case has("model_id") && has("none"):
		return "ConfigurationError"
	}
	return "Error"
}

func errorDetail(err error) string { return causeText(err) }

func extractErrorDetails(err error) string {
	parts := []string{err.Error()}
	if name := activityName(err); name != "" {
		parts = append(parts, "activity="+name)
	}
	if a := appErr(err); a != nil {
		parts = append(parts, "cause="+a.Message())
		if a.Type() != "" {
			parts = append(parts, "cause_type="+a.Type())
		}
	}
	return strings.Join(parts, " | ")
}
