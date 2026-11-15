package service

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/transport"
)

// TestResult is ModelInstanceTestResponse; the provider's own words never reach it.
type TestResult struct {
	Success         bool
	Message         string
	ResponseContent *string
	ErrorType       *string
	ProviderType    *string
	ModelName       *string
	Cost            *money.Decimal
	TokensUsed      *int64
}

func ptr[T any](v T) *T { return &v }

// TestModel is validate_model_instance: one 50-token chat call on the
// configuration's key, unpriced, nothing written or billed.
// A test asks for 50 tokens: its answer is small and quick or the provider misbehaves.
const (
	testDeadline        = 60 * time.Second
	testBodyLimit int64 = 1 << 20
)

func (s *Service) TestModel(ctx context.Context, configID, specID uuid.UUID, message *string) (TestResult, error) {
	ws, userID, err := caller(ctx)
	if err != nil {
		return TestResult{}, err
	}
	v, ok, err := s.view(ctx, ws, configID)
	if err != nil {
		return TestResult{}, err
	}
	if !ok {
		return TestResult{}, &HTTPError{Status: 404, Detail: "Provider config not found"}
	}
	if v.PlatformManaged() {
		return TestResult{}, &HTTPError{Status: 403, Detail: "Testing is not available for platform-supplied providers."}
	}
	spec, ok, err := s.d.Catalog.UsableModelSpec(ctx, ws, specID)
	if err != nil {
		return TestResult{}, err
	}
	if !ok {
		return TestResult{}, &HTTPError{Status: 404, Detail: "Model spec not found"}
	}
	if spec.Kind != "chat" {
		return TestResult{Success: false, Message: fmt.Sprintf("A %s model cannot be tested with a chat message", spec.Kind),
			ErrorType: ptr("UnsupportedModelKind"), ModelName: ptr(spec.ModelName)}, nil
	}
	if v.Spec == nil {
		return TestResult{}, fmt.Errorf("provider spec %s of configuration %s is missing", v.ProviderSpecID, v.ID)
	}
	providerType := v.Spec.ProviderType
	if providerType == "" {
		return TestResult{}, &HTTPError{Status: 400, Detail: "Provider type is not configured"}
	}
	modelName := spec.ModelName
	fail := func(msg, typ string) TestResult {
		return TestResult{Message: msg, ErrorType: ptr(typ), ProviderType: ptr(providerType), ModelName: ptr(modelName)}
	}
	result, err := s.testCall(ctx, userID, v, providerType, modelName, message)
	if err == nil {
		return result, nil
	}
	if errors.Is(err, context.Canceled) {
		return TestResult{}, err
	}
	slog.ErrorContext(ctx, "LLM test failed", "error_type", transport.PyType(err), "error", err)
	return classifyTest(err, fail), nil
}

func (s *Service) testCall(ctx context.Context, userID string, v ConfigView, providerType, modelName string, message *string) (TestResult, error) {
	key := ""
	if v.APIKey != nil && *v.APIKey != "" {
		ws, _, err := caller(ctx)
		if err != nil {
			return TestResult{}, err
		}
		if key, err = s.readSecret(ctx, ws, userID, *v.APIKey); err != nil {
			return TestResult{}, err
		}
	}
	profile, err := domainProfile(*v.Spec)
	if err != nil {
		return TestResult{}, err
	}
	endpoint := str(v.EndpointURL)
	if key == "" && profile.RequiresAPIKey() {
		return TestResult{Message: "No API key found for this provider configuration", ErrorType: ptr("MissingAPIKey"),
			ProviderType: ptr(providerType), ModelName: ptr(modelName)}, nil
	}
	if profile.RequiresEndpointURL() && endpoint == "" {
		return TestResult{Message: fmt.Sprintf("%s is self-hosted and has no public API address; configure the endpoint URL explicitly.", providerType),
			ErrorType: ptr("MissingEndpoint"), ProviderType: ptr(providerType), ModelName: ptr(modelName)}, nil
	}
	slog.InfoContext(ctx, "Testing LLM configuration", "provider_type", providerType, "model_name", modelName)
	model := transport.Model{
		ProviderType: providerType, ModelName: modelName, APIKey: key, EndpointURL: s.localEndpoint(endpoint),
		Profile: profile, Transport: s.roundTripper(str(v.ManagedBy)),
		Deadline: testDeadline, BodyLimit: testBodyLimit,
	}
	msg := api.Message{Role: "user"}
	if message != nil {
		msg.Content = *message
	}
	var content strings.Builder
	cost := money.FromInt(0)
	var tokens int64
	err = model.Stream(ctx, transport.Request{Messages: []api.Message{msg}, MaxTokens: 50}, func(d transport.Delta) error {
		content.WriteString(d.Content)
		if d.Usage != nil {
			tokens, cost = d.Usage.Total, d.Cost
		}
		return nil
	})
	if err != nil {
		return TestResult{}, err
	}
	return TestResult{Success: true, Message: "LLM test successful", ResponseContent: ptr(content.String()),
		ProviderType: ptr(providerType), ModelName: ptr(modelName), Cost: &cost, TokensUsed: &tokens}, nil
}

// classifyTest is the route's keyword matching: the platform's own words only (GHSA-pprc-x767-m6jg).
func classifyTest(err error, fail func(msg, typ string) TestResult) TestResult {
	text := strings.ToLower(err.Error())
	typ := transport.PyType(err)
	switch {
	case typ == "UnsafeUrlError":
		return fail("The endpoint URL points to an address this deployment does not call", "EndpointRefused")
	case strings.Contains(typ, "AuthenticationError") || strings.Contains(text, "api_key"):
		return fail("Authentication failed - please check your API key", "AuthenticationError")
	case strings.Contains(typ, "RateLimitError") || strings.Contains(text, "rate limit"):
		return fail("Rate limit exceeded - please try again later", "RateLimitError")
	case strings.Contains(text, "quota") || strings.Contains(text, "billing"):
		return fail("Quota exceeded or billing issue", "QuotaError")
	case strings.Contains(text, "model") && (strings.Contains(text, "not found") || strings.Contains(text, "does not exist")):
		return fail("Model not found or not available", "ModelNotFoundError")
	case strings.Contains(text, "connection") || strings.Contains(text, "timeout"):
		return fail("Connection failed - please check endpoint URL", "ConnectionError")
	}
	var h *transport.ProviderHTTPError
	if errors.As(err, &h) {
		return fail(fmt.Sprintf("Test failed: the provider answered with HTTP %d", h.StatusCode), typ)
	}
	return fail("Test failed: the provider call did not complete", typ)
}
