package transport

import (
	"errors"
	"fmt"
	"reflect"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/domain"
)

func httpErr(status int, message string) error {
	return &ProviderHTTPError{StatusCode: status, ProviderMessage: message}
}

func pyErr(typ, message string) error { return &PyError{Type: typ, Msg: message} }

func wrapped(inner error) error {
	return &PyError{Type: "RuntimeError", Msg: "LLM call failed", Cause: inner}
}

func transportErr(kind string, timeout bool, message string) error {
	return &TransportError{Kind: kind, Timeout: timeout, Err: errors.New(message)}
}

func TestKnownCausesHaveTheirOwnMessage(t *testing.T) {
	cases := []struct {
		name  string
		err   error
		cause string
		says  string
	}{
		{"no_usage", pyErr("RuntimeError", "LLM usage accounting unavailable; token and cost policy cannot be enforced"), "usage_unavailable", "did not report token usage"},
		{"customer_pricing", pyErr("RuntimeError", "LLM usage accounting unavailable: customer pricing failed: rates offline"), "pricing_unavailable", "billing"},
		{"decrypt", pyErr("ValueError", "Failed to decrypt secret. Key may have changed."), "credentials_undecryptable", "re-enter"},
		{"policy", pyErr("ConfigurationError", "effective policy is missing required runtime limit max_tokens"), "policy_incomplete", "per-call token limit"},
		{"credits_in_400_body", httpErr(400, "Insufficient credits"), "provider_out_of_credits", "out of credits"},
		{"code_402_in_400_body", httpErr(400, `{"error":{"code":402}}`), "provider_out_of_credits", "out of credits"},
		{"status_402", httpErr(402, "This request requires more credits"), "provider_out_of_credits", "out of credits"},
		{"quota_exceeded", httpErr(400, "Quota exceeded for this project"), "provider_out_of_credits", "out of credits"},
		{"auth_401", httpErr(401, "Incorrect API key provided"), "provider_auth", "api key"},
		{"auth_403", httpErr(403, "Your organization does not have access to this model"), "provider_auth", "api key"},
		{"rate_limit", httpErr(429, "Too many requests"), "rate_limited", "try again"},
		{"not_found", httpErr(404, "The model `gpt-9` does not exist"), "model_not_found", "not found"},
		{"deprecated", httpErr(404, "The model `gpt-3` has been deprecated"), "model_deprecated", "deprecated"},
		{"context_window_openai", httpErr(400, "This model's maximum context length is 8192 tokens. However, you requested 9000"), "context_window_exceeded", "context window"},
		{"context_window_anthropic", httpErr(400, "prompt is too long: 210000 tokens > 200000 maximum"), "context_window_exceeded", "context window"},
		{"context_window_413", httpErr(413, "Input is too long for requested model."), "context_window_exceeded", "context window"},
		{"context_window_422", httpErr(422, "The input or output tokens must be reduced: too many tokens"), "context_window_exceeded", "context window"},
		{"context_window_no_status", pyErr("RuntimeError", "context_length_exceeded"), "context_window_exceeded", "context window"},
		{"content_policy", httpErr(400, "Your request was rejected as a result of our safety system."), "provider_content_policy", "content policy"},
		{"connect_timeout", transportErr("ConnectTimeout", true, ""), "timeout", "timed out"},
		{"read_timeout", transportErr("ReadTimeout", true, "read operation"), "timeout", "timed out"},
		{"status_408", httpErr(408, "Request Timeout"), "timeout", "timed out"},
		{"timed_out_text", pyErr("RuntimeError", "the call timed out"), "timeout", "timed out"},
		{"status_503", httpErr(503, "Service Unavailable"), "provider_unavailable", "unavailable"},
		{"anthropic_overloaded_529", httpErr(529, "Overloaded"), "provider_unavailable", "unavailable"},
		{"status_500", httpErr(500, "Internal server error"), "provider_unavailable", "unavailable"},
		{"connect_error", transportErr("ConnectError", false, "[Errno 111] Connection refused"), "provider_unavailable", "unavailable"},
		{"transport_error", transportErr("RemoteProtocolError", false, "peer closed connection without sending complete message"), "provider_unavailable", "unavailable"},
		{"stream_error_string_code", httpErr(400, "context_length_exceeded: Too long"), "context_window_exceeded", "context window"},
		{"stream_error_quota_code", httpErr(402, "insufficient_quota: Account not active"), "provider_out_of_credits", "out of credits"},
	}
	for _, tc := range cases {
		f, ok := Classify(tc.err)
		if !ok {
			t.Errorf("%s: not classified", tc.name)
			continue
		}
		if f.Cause != tc.cause || !strings.Contains(strings.ToLower(f.Message), tc.says) || strings.Contains(f.Message, "Failed to get a response") {
			t.Errorf("%s: got %+v", tc.name, f)
		}
	}
}

func TestABuiltinTimeoutErrorIsATimeout(t *testing.T) {
	f, ok := Classify(pyErr("TimeoutError", ""))
	if !ok || f.Cause != "timeout" {
		t.Errorf("differs from Python: isinstance(error, TimeoutError) classifies as timeout; Go gives %+v, %v", f, ok)
	}
}

func TestErrorTypesAndRetryability(t *testing.T) {
	cases := map[string]struct {
		errType   string
		retryable bool
	}{
		"credentials_undecryptable": {"CredentialsUnreadable", false}, "pricing_unavailable": {"BillingUnavailable", false},
		"usage_unavailable": {"UsageUnavailable", false}, "policy_incomplete": {"ConfigurationError", false},
		"context_window_exceeded": {"ContextWindowExceeded", false}, "provider_out_of_credits": {"ProviderQuotaExceeded", false},
		"provider_auth": {"AuthenticationError", false}, "rate_limited": {"RateLimitError", true},
		"model_deprecated": {"ModelDeprecated", false}, "model_not_found": {"ModelNotFound", false},
		"provider_content_policy": {"ContentPolicyViolation", false}, "timeout": {"TimeoutError", true},
		"provider_bad_request": {"ProviderBadRequest", false}, "provider_unavailable": {"ProviderUnavailable", true},
	}
	errs := []error{
		pyErr("ValueError", "failed to decrypt"), pyErr("X", "customer pricing failed"), pyErr("X", "returned no usage"),
		pyErr("X", "effective policy is missing required runtime limit"), httpErr(400, "too many tokens"), httpErr(402, "x"),
		httpErr(401, "x"), httpErr(429, "x"), httpErr(400, "deprecated"), httpErr(404, "x"), httpErr(400, "content_filter"),
		httpErr(408, "x"), httpErr(409, "x"), httpErr(502, "x"),
	}
	seen := map[string]bool{}
	for _, err := range errs {
		f, ok := Classify(err)
		if !ok {
			t.Errorf("%v: not classified", err)
			continue
		}
		want, known := cases[f.Cause]
		if !known || f.ErrorType != want.errType || f.Retryable != want.retryable {
			t.Errorf("%v: got %+v", err, f)
		}
		seen[f.Cause] = true
	}
	if len(seen) != len(cases) {
		t.Errorf("covered %d of %d causes", len(seen), len(cases))
	}
}

func TestAProvider400CarriesTheProvidersOwnWords(t *testing.T) {
	f, ok := Classify(httpErr(400, "Invalid value for 'tools[0].name'"))
	if !ok || f.Cause != "provider_bad_request" || f.Message != "The model provider rejected the request: Invalid value for 'tools[0].name'" {
		t.Errorf("got %+v", f)
	}
	f, _ = Classify(httpErr(400, "  max_tokens is too large  "))
	if f.Message != "The model provider rejected the request: max_tokens is too large" {
		t.Errorf("got %q", f.Message)
	}
}

func TestTheProvidersWordsAreCutAt300Characters(t *testing.T) {
	f, _ := Classify(httpErr(400, strings.Repeat("ж", 400)))
	if want := "The model provider rejected the request: " + strings.Repeat("ж", 300); f.Message != want {
		t.Errorf("message has %d runes", len([]rune(f.Message)))
	}
}

func TestAnyOtherClientErrorIsABadRequest(t *testing.T) {
	for _, status := range []int{409, 413, 415, 422} {
		f, ok := Classify(httpErr(status, "Request entity rejected"))
		if !ok || f.Cause != "provider_bad_request" || f.Retryable {
			t.Errorf("%d: got %+v", status, f)
		}
	}
}

func TestAContextPhraseOnARateLimitIsStillARateLimit(t *testing.T) {
	if f, _ := Classify(httpErr(429, "too many tokens per minute")); f.Cause != "rate_limited" {
		t.Errorf("got %+v", f)
	}
	if f, _ := Classify(httpErr(429, "Quota exceeded for metric: requests per minute")); f.Cause != "rate_limited" || !f.Retryable {
		t.Errorf("got %+v", f)
	}
}

func TestAContentPolicyPhraseOnAServerErrorIsUnavailable(t *testing.T) {
	if f, _ := Classify(httpErr(500, "content_filter backend down")); f.Cause != "provider_unavailable" {
		t.Errorf("got %+v", f)
	}
}

func TestTheCauseIsFoundThroughAWrappingError(t *testing.T) {
	if f, _ := Classify(wrapped(httpErr(401, "bad key"))); f.Cause != "provider_auth" {
		t.Errorf("got %+v", f)
	}
	if f, _ := Classify(fmt.Errorf("activity: %w", httpErr(401, "bad key"))); f.Cause != "provider_auth" {
		t.Errorf("fmt wrap: got %+v", f)
	}
	f, ok := Classify(wrapped(transportErr("ConnectError", false, "connection refused")))
	if !ok || f.Cause != "provider_unavailable" || !f.Retryable {
		t.Errorf("got %+v", f)
	}
}

func TestTheFirstStatusInTheChainWins(t *testing.T) {
	err := &PyError{Type: "RuntimeError", Msg: "x", Cause: &ProviderHTTPError{StatusCode: 401, ProviderMessage: "a"}}
	outer := fmt.Errorf("y: %w", err)
	if f, _ := Classify(outer); f.Cause != "provider_auth" {
		t.Errorf("got %+v", f)
	}
}

func TestABodyEchoedInAnErrorReducesToTheProvidersSentence(t *testing.T) {
	echo := &PyError{Type: "HTTPStatusError", Msg: `HTTPStatusError: {"error":{"message":"Unknown parameter: 'foo'"}}`, Cause: httpErr(400, " ")}
	f, ok := Classify(wrapped(echo))
	if !ok || f.Cause != "provider_bad_request" || !strings.HasSuffix(f.Message, "Unknown parameter: 'foo'") {
		t.Errorf("got %+v", f)
	}
}

func TestSDKPrefixesAreStrippedFromTheProvidersWords(t *testing.T) {
	err := &PyError{Type: "RuntimeError", Msg: "BadRequestError: ValueError: invalid thing", Cause: httpErr(409, "")}
	if f, _ := Classify(err); f.Message != "The model provider rejected the request: invalid thing" {
		t.Errorf("got %q", f.Message)
	}
	err = &PyError{Type: "RuntimeError", Msg: `{"message": "bad \"quoted\" value"}`, Cause: httpErr(418, "")}
	if f, _ := Classify(err); f.Message != `The model provider rejected the request: bad "quoted" value` {
		t.Errorf("got %q", f.Message)
	}
}

func TestAnErrorThatIsNotAProviderAnswerIsNotClassified(t *testing.T) {
	for _, err := range []error{
		pyErr("RuntimeError", "something odd"),
		&UnsafeURLError{Msg: EndpointRefused},
		pyErr("ValueError", "No base URL configured for direct HTTP completion call"),
		&NoAddressError{ProviderType: "ollama"},
		errors.New("plain"),
	} {
		if f, ok := Classify(err); ok {
			t.Errorf("%v: classified as %+v", err, f)
		}
	}
}

func TestPermanentAndTransientCauses(t *testing.T) {
	for _, err := range []error{pyErr("ValueError", "Failed to decrypt secret. Key may have changed."), httpErr(400, "bad"),
		httpErr(401, "invalid key"), httpErr(402, "no credits"), httpErr(404, "no such model"), httpErr(400, "prompt is too long")} {
		if f, ok := Classify(err); !ok || f.Retryable {
			t.Errorf("%v: got %+v", err, f)
		}
	}
	for _, err := range []error{httpErr(429, "slow down"), httpErr(529, "Overloaded"), transportErr("ReadTimeout", true, "read"),
		transportErr("ConnectError", false, "refused")} {
		if f, ok := Classify(err); !ok || !f.Retryable {
			t.Errorf("%v: got %+v", err, f)
		}
	}
}

func TestTheDetailRoundTripsAsPlainData(t *testing.T) {
	f, _ := Classify(httpErr(401, "invalid key"))
	want := map[string]any{"llm_failure": map[string]any{"cause": "provider_auth", "message": f.Message, "error_type": "AuthenticationError", "retryable": false}}
	if !reflect.DeepEqual(f.Detail(), want) {
		t.Errorf("detail = %+v", f.Detail())
	}
	assertJSON(t, "detail", f.Detail(), `{"llm_failure":{"cause":"provider_auth","message":"The model provider rejected the API key. Check the key in the provider settings.","error_type":"AuthenticationError","retryable":false}}`)
}

func TestPyType(t *testing.T) {
	cases := []struct {
		err  error
		want string
	}{
		{httpErr(400, "x"), "LLMProviderHTTPError"},
		{&UnsafeURLError{Msg: "x"}, "UnsafeUrlError"},
		{&NoAddressError{ProviderType: "x"}, "ValueError"},
		{transportErr("ReadTimeout", true, "x"), "ReadTimeout"},
		{pyErr("KeyError", "x"), "KeyError"},
		{&domain.ReasoningSettingError{Msg: "x"}, "ReasoningSettingError"},
		{fmt.Errorf("w: %w", httpErr(400, "x")), "LLMProviderHTTPError"},
		{errors.New("x"), "Exception"},
	}
	for _, tc := range cases {
		if got := PyType(tc.err); got != tc.want {
			t.Errorf("PyType(%v) = %q, want %q", tc.err, got, tc.want)
		}
	}
}

func TestCallFailure(t *testing.T) {
	auth := httpErr(401, "invalid key")
	var app *durable.ApplicationError
	if !errors.As(CallFailure(auth), &app) {
		t.Fatal("not an ApplicationError")
	}
	if app.Type != "LLMProviderHTTPError" || app.Message != "Provider returned HTTP 401: invalid key" || !app.NonRetryable || !errors.Is(app, auth) {
		t.Errorf("auth = %+v", app)
	}
	f, _ := Classify(auth)
	if !reflect.DeepEqual(app.Details, []any{f.Detail()}) {
		t.Errorf("details = %+v", app.Details)
	}

	if !errors.As(CallFailure(httpErr(429, "slow down")), &app) || app.NonRetryable || len(app.Details) != 1 {
		t.Errorf("rate limit = %+v", app)
	}
	if !errors.As(CallFailure(transportErr("ReadTimeout", true, "read")), &app) || app.Type != "ReadTimeout" || app.NonRetryable {
		t.Errorf("timeout = %+v", app)
	}

	reasoning := &domain.ReasoningSettingError{Msg: "the Anthropic transport does not take reasoning settings yet"}
	if !errors.As(CallFailure(reasoning), &app) || app.Type != "ReasoningSettingError" || !app.NonRetryable || app.Details != nil || app.Message != reasoning.Msg {
		t.Errorf("reasoning = %+v", app)
	}

	already := &durable.ApplicationError{Type: "SpendCapReachedError", Message: "cap", NonRetryable: true}
	var got *durable.ApplicationError
	if !errors.As(CallFailure(already), &got) || got != already {
		t.Errorf("an ApplicationError is rebuilt: %+v", got)
	}
}

func TestCallFailureOfAnUnclassifiedErrorUsesTheRetryHeuristics(t *testing.T) {
	cases := []struct {
		err          error
		nonRetryable bool
	}{
		{pyErr("RuntimeError", "something odd"), false},
		{&UnsafeURLError{Msg: EndpointRefused}, false},
		{&NoAddressError{ProviderType: "ollama"}, false},
		{pyErr("ValueError", "model foo does not exist"), true},
		{pyErr("ValueError", "invalid model name"), true},
		{pyErr("RuntimeError", "billing hiccup"), true},
		{pyErr("RuntimeError", "missing api_key"), true},
		{pyErr("AuthenticationError", "nope"), true},
		{pyErr("RuntimeError", "exceeded something, code 429"), false},
		{pyErr("RateLimitError", "quota"), false},
	}
	for _, tc := range cases {
		if _, ok := Classify(tc.err); ok {
			t.Errorf("%v: classified", tc.err)
			continue
		}
		var app *durable.ApplicationError
		if !errors.As(CallFailure(tc.err), &app) {
			t.Fatalf("%v: not an ApplicationError", tc.err)
		}
		if app.NonRetryable != tc.nonRetryable || app.Details != nil || app.Type != PyType(tc.err) || app.Message != tc.err.Error() {
			t.Errorf("%v: got %+v", tc.err, app)
		}
	}
}
