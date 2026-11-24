package handlers

import (
	"context"
	"net/http"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/models"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
)

// signInBody is ChatGPTSignInRequest.
func signInBody(v any, in *input, errs *[]httpx.FieldError) any {
	o, ok := model(v, errs)
	if !ok {
		return nil
	}
	for _, f := range []struct {
		key string
		dst *string
	}{{"device_auth_id", &in.deviceAuthID}, {"user_code", &in.userCode}} {
		s, set := str(o, f.key, 1, 512, false, errs)
		if !set {
			*errs = append(*errs, httpx.Missing("body", f.key))
		} else if s != nil {
			*f.dst = *s
		}
	}
	return map[string]any{}
}

func (s *Server) StartChatgptSignInV1ProviderConfigsConfigIdChatgptSignInPost(ctx context.Context, r gen.StartChatgptSignInV1ProviderConfigsConfigIdChatgptSignInPostRequestObject) (gen.StartChatgptSignInV1ProviderConfigsConfigIdChatgptSignInPostResponseObject, error) {
	d, err := s.svc.StartChatGPTSignIn(ctx, r.ConfigId)
	if err != nil {
		return nil, err
	}
	return ok(wirejson.Object{
		{Key: "device_auth_id", Value: d.DeviceAuthID},
		{Key: "user_code", Value: d.UserCode},
		{Key: "verification_uri", Value: d.VerificationURL},
		{Key: "interval", Value: d.Interval},
	}), nil
}

func (s *Server) CompleteChatgptSignInV1ProviderConfigsConfigIdChatgptSignInCompletePost(ctx context.Context, r gen.CompleteChatgptSignInV1ProviderConfigsConfigIdChatgptSignInCompletePostRequestObject) (gen.CompleteChatgptSignInV1ProviderConfigsConfigIdChatgptSignInCompletePostResponseObject, error) {
	in := inputFrom(ctx)
	done, err := s.svc.FinishChatGPTSignIn(ctx, r.ConfigId, in.deviceAuthID, in.userCode)
	if err != nil {
		return nil, err
	}
	return ok(wirejson.Object{{Key: "signed_in", Value: done}}), nil
}

func (x response) VisitStartChatgptSignInV1ProviderConfigsConfigIdChatgptSignInPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitCompleteChatgptSignInV1ProviderConfigsConfigIdChatgptSignInCompletePostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
