package transport

import (
	"encoding/json"
	"errors"
	"regexp"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
)

// PyError is an error Python raises under its own class name.
type PyError struct {
	Type, Msg string
	Cause     error
}

func (e *PyError) Error() string  { return e.Msg }
func (e *PyError) Unwrap() error  { return e.Cause }
func (e *PyError) PyType() string { return e.Type }

func (e *ProviderHTTPError) PyType() string { return "LLMProviderHTTPError" }
func (e *UnsafeURLError) PyType() string    { return "UnsafeUrlError" }
func (e *NoAddressError) PyType() string    { return "ValueError" }
func (e *TransportError) PyType() string    { return e.Kind }

type pyTyped interface{ PyType() string }

// PyType is the Python class name of err, "Exception" when it has none.
func PyType(err error) string {
	var t pyTyped
	if errors.As(err, &t) {
		return t.PyType()
	}
	return "Exception"
}

// Failure is LLMFailure: a classified model-call failure.
type Failure struct {
	Cause, Message, ErrorType string
	Retryable                 bool
}

// Detail is LLMFailure.as_detail.
func (f Failure) Detail() map[string]any {
	return map[string]any{"llm_failure": map[string]any{
		"cause": f.Cause, "message": f.Message, "error_type": f.ErrorType, "retryable": f.Retryable,
	}}
}

const (
	providerMessageLimit = 300
	billingUnavailable   = "Billing is temporarily unavailable. Please try again later."
	outOfCredits         = "The model provider's account is out of credits or quota, so it refused the call. Top up the provider account or choose a different model."
)

func outOfCreditsPhrases() []string {
	return []string{"insufficient credits", "insufficient balance", "insufficient funds", "insufficient_quota",
		"exceeded your current quota", "out of credits", "requires more credits", "payment required", "no resource package", "please recharge"}
}

func contextWindowPhrases() []string {
	return []string{"context_length_exceeded", "maximum context length", "maximum context limit",
		"longer than the model's context length", "exceed context limit", "exceeds the available context size",
		"exceeds the maximum number of tokens allowed", "input tokens exceed the configured limit", "prompt is too long",
		"input is too long", "too many tokens"}
}

func contentPolicyPhrases() []string {
	return []string{"content_policy_violation", "responsibleaipolicyviolation", "content management policy",
		"content_filter", "as a result of our safety system"}
}

var (
	jsonMessage     = regexp.MustCompile(`"message"\s*:\s*("(?:[^"\\]|\\.)*")`)
	jsonCode402     = regexp.MustCompile(`"code"\s*:\s*"?402\b`)
	exceptionPrefix = regexp.MustCompile(`^\w+(?:Error|Exception)?:\s*`)
)

// chain is the error and every typed error it wraps, outermost first; an
// untyped innermost cause closes it, as Python's __cause__/__context__ chain would.
func chain(err error) []error {
	var out []error
	for cur := err; cur != nil; cur = errors.Unwrap(cur) {
		if _, ok := cur.(pyTyped); ok || len(out) == 0 {
			out = append(out, cur)
		}
	}
	return out
}

func typeName(err error) string {
	if t, ok := err.(pyTyped); ok {
		return t.PyType()
	}
	return "Exception"
}

func says(text string, phrases []string) bool {
	for _, p := range phrases {
		if strings.Contains(text, p) {
			return true
		}
	}
	return false
}

func providerMessage(errs []error) string {
	for _, e := range errs {
		var h *ProviderHTTPError
		if errors.As(e, &h) && strings.TrimSpace(h.ProviderMessage) != "" {
			return truncate(strings.TrimSpace(h.ProviderMessage), providerMessageLimit)
		}
	}
	text := errs[0].Error()
	for _, e := range errs {
		if jsonMessage.MatchString(e.Error()) {
			text = e.Error()
			break
		}
	}
	if m := jsonMessage.FindStringSubmatch(text); m != nil {
		var s string
		if err := json.Unmarshal([]byte(m[1]), &s); err == nil {
			text = s
		} else {
			text = strings.Trim(m[1], `"`)
		}
	}
	for prev := ""; prev != text; {
		prev = text
		if loc := exceptionPrefix.FindStringIndex(text); loc != nil {
			text = text[loc[1]:]
		}
		text = strings.TrimSpace(text)
	}
	return truncate(text, providerMessageLimit)
}

// Classify is classify_llm_failure; false when the failure is not one it recognises.
func Classify(err error) (Failure, bool) {
	errs := chain(err)
	parts := make([]string, len(errs))
	status := 0
	timeout, transport := false, false
	for i, e := range errs {
		parts[i] = typeName(e) + " " + e.Error()
		var h *ProviderHTTPError
		if status == 0 && errors.As(e, &h) {
			status = h.StatusCode
		}
		if typeName(e) == "TimeoutError" {
			timeout = true
		}
		var te *TransportError
		if errors.As(e, &te) {
			transport = true
			timeout = timeout || te.Timeout
		}
	}
	text := strings.ToLower(strings.Join(parts, " "))
	hasStatus := status != 0

	switch {
	case strings.Contains(text, "failed to decrypt"):
		return Failure{"credentials_undecryptable", "The provider's API key can no longer be decrypted (the encryption key changed). Re-enter the key in the provider settings.", "CredentialsUnreadable", false}, true
	case strings.Contains(text, "customer pricing failed"):
		return Failure{"pricing_unavailable", billingUnavailable, "BillingUnavailable", false}, true
	case strings.Contains(text, "usage accounting unavailable") || strings.Contains(text, "returned no usage"):
		return Failure{"usage_unavailable", "The model provider did not report token usage for this call, so its cost cannot be accounted and the run was stopped. Try again or choose a different model.", "UsageUnavailable", false}, true
	case strings.Contains(text, "effective policy is missing required runtime limit"):
		return Failure{"policy_incomplete", "The run's policy sets no per-call token limit, so the model cannot be called. Check the workspace policy.", "ConfigurationError", false}, true
	}
	rejected := !hasStatus || status == 400 || status == 413 || status == 422
	switch {
	case rejected && says(text, contextWindowPhrases()):
		return Failure{"context_window_exceeded", "The conversation no longer fits the model's context window. Start a new run or choose a model with a larger context window.", "ContextWindowExceeded", false}, true
	case status == 402 || jsonCode402.MatchString(text) || says(text, outOfCreditsPhrases()):
		return Failure{"provider_out_of_credits", outOfCredits, "ProviderQuotaExceeded", false}, true
	case status == 401 || status == 403 || strings.Contains(text, "invalid api key") || strings.Contains(text, "incorrect api key") || strings.Contains(text, "unauthorized"):
		return Failure{"provider_auth", "The model provider rejected the API key. Check the key in the provider settings.", "AuthenticationError", false}, true
	case status == 429 || strings.Contains(text, "rate limit") || strings.Contains(text, "too many requests"):
		return Failure{"rate_limited", "The model provider is rate-limiting requests. Please try again in a moment.", "RateLimitError", true}, true
	case strings.Contains(text, "quota exceeded"):
		return Failure{"provider_out_of_credits", outOfCredits, "ProviderQuotaExceeded", false}, true
	case strings.Contains(text, "deprecated"):
		return Failure{"model_deprecated", "The configured model has been deprecated by the provider. Please select a different model.", "ModelDeprecated", false}, true
	case status == 404:
		return Failure{"model_not_found", "The configured model was not found. Please check the model name or select a different one.", "ModelNotFound", false}, true
	case rejected && says(text, contentPolicyPhrases()):
		return Failure{"provider_content_policy", "The model provider refused the request under its content policy.", "ContentPolicyViolation", false}, true
	case status == 408 || timeout || strings.Contains(text, "timed out"):
		return Failure{"timeout", "The AI model request timed out. Please try again.", "TimeoutError", true}, true
	case hasStatus && status >= 400 && status < 500:
		return Failure{"provider_bad_request", "The model provider rejected the request: " + providerMessage(errs), "ProviderBadRequest", false}, true
	case (hasStatus && status >= 500) || transport:
		return Failure{"provider_unavailable", "The model provider is unavailable right now. Please try again later.", "ProviderUnavailable", true}, true
	}
	return Failure{}, false
}

// nonRetryable is event_publisher._is_non_retryable_error.
func nonRetryable(err error) bool {
	s := strings.ToLower(err.Error())
	t := strings.ToLower(PyType(err))
	if strings.Contains(t, "ratelimiterror") || strings.Contains(s, "rate limit") || strings.Contains(s, "too many requests") || strings.Contains(s, "429") {
		return false
	}
	auth := strings.Contains(t, "authenticationerror") || strings.Contains(s, "api_key") || strings.Contains(s, "authentication") ||
		strings.Contains(s, "unauthorized") || strings.Contains(s, "401")
	quota := strings.Contains(s, "quota") || strings.Contains(s, "billing") || strings.Contains(s, "exceeded") ||
		strings.Contains(s, "insufficient funds") || strings.Contains(s, "insufficient balance") ||
		strings.Contains(s, "no resource package") || strings.Contains(s, "please recharge")
	model := strings.Contains(s, "model") && (strings.Contains(s, "not found") || strings.Contains(s, "does not exist") || strings.Contains(s, "invalid"))
	accounting := strings.Contains(s, "usage accounting unavailable") || strings.Contains(s, "returned no usage") ||
		strings.Contains(s, "effective policy is missing required runtime limit")
	return accounting || auth || quota || model
}

// CallFailure is the activity failure _model_call_failure builds for err, before
// runs prefixes its message: typed as the Python exception, the classified
// cause in its details. A ReasoningSettingError is never retried.
func CallFailure(err error) error {
	var app *durable.ApplicationError
	if errors.As(err, &app) {
		return err
	}
	typ := PyType(err)
	if typ == "ReasoningSettingError" {
		return &durable.ApplicationError{Type: typ, Message: err.Error(), NonRetryable: true, Cause: err}
	}
	if f, ok := Classify(err); ok {
		return &durable.ApplicationError{Type: typ, Message: err.Error(), NonRetryable: !f.Retryable, Details: []any{f.Detail()}, Cause: err}
	}
	return &durable.ApplicationError{Type: typ, Message: err.Error(), NonRetryable: nonRetryable(err), Cause: err}
}
