package domain

// Run failure reasons the run transition counter is labelled with (telemetry.py RunFailureReason).
const (
	RunFailureNone          = "none"
	RunFailureCancelled     = "cancelled"
	RunFailureLimit         = "limit"
	RunFailurePolicy        = "policy"
	RunFailureAgent         = "agent"
	RunFailureInputTimeout  = "input_timeout"
	RunFailureProvider      = "provider"
	RunFailureConfiguration = "configuration"
	RunFailureDependency    = "dependency"
	RunFailureTimeout       = "timeout"
	RunFailureInternal      = "internal"
)

// runFailureCode is the closed reason a known failure code counts under.
func runFailureCode(code string) (string, bool) {
	switch code {
	case "cancelled":
		return RunFailureCancelled, true
	case "budget_exceeded", "token_limit", "tool_call_limit", "iteration_limit", "monthly_spend_cap_exceeded", "llm_run_cap_exceeded":
		return RunFailureLimit, true
	case "governance_denied", "blocked", "capability_unavailable":
		return RunFailurePolicy, true
	case "validation_failed", "unmet_prerequisite", "missing_final_response", "task_unsuccessful":
		return RunFailureAgent, true
	case "input_timeout":
		return RunFailureInputTimeout, true
	case "context_window_exceeded", "provider_out_of_credits", "provider_auth", "rate_limited", "model_deprecated", "model_not_found", "provider_content_policy", "provider_bad_request", "provider_unavailable", "usage_unavailable":
		return RunFailureProvider, true
	case "credentials_undecryptable", "model_unpriced", "policy_incomplete":
		return RunFailureConfiguration, true
	case "pricing_unavailable", "dependency_unavailable":
		return RunFailureDependency, true
	case "timeout":
		return RunFailureTimeout, true
	default:
		return "", false
	}
}

// RunFailureReason is the closed failure_reason a status update counts
// under: any reason on a blocked run is a policy one, a code nobody mapped is internal.
func RunFailureReason(status, failureReason string) string {
	if failureReason == "" {
		switch status {
		case "failed":
			return RunFailureInternal
		case "cancelled":
			return RunFailureCancelled
		case "blocked":
			return RunFailurePolicy
		}
		return RunFailureNone
	}
	if known, ok := runFailureCode(failureReason); ok {
		return known
	}
	if status == "blocked" {
		return RunFailurePolicy
	}
	return RunFailureInternal
}

// TerminalRunStatus: a status after which the run's duration is recorded.
func TerminalRunStatus(status string) bool {
	switch status {
	case "completed", "failed", "cancelled", "blocked":
		return true
	}
	return false
}
