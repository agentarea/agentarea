package handlers

import (
	"context"
	"net/http"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/models"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/service"
)

func (s *Server) StartChatgptSignInV1ProviderConfigsConfigIdChatgptSignInPost(ctx context.Context, r gen.StartChatgptSignInV1ProviderConfigsConfigIdChatgptSignInPostRequestObject) (gen.StartChatgptSignInV1ProviderConfigsConfigIdChatgptSignInPostResponseObject, error) {
	d, err := s.svc.StartChatGPTSignIn(ctx, r.ConfigId)
	if err != nil {
		return nil, err
	}
	return ok(wirejson.Object{
		{Key: "user_code", Value: d.UserCode},
		{Key: "verification_uri", Value: d.VerificationURL},
		{Key: "interval", Value: d.Interval},
		{Key: "expires_in", Value: service.ChatGPTDeviceCodeSeconds},
	}), nil
}

func (s *Server) CompleteChatgptSignInV1ProviderConfigsConfigIdChatgptSignInCompletePost(ctx context.Context, r gen.CompleteChatgptSignInV1ProviderConfigsConfigIdChatgptSignInCompletePostRequestObject) (gen.CompleteChatgptSignInV1ProviderConfigsConfigIdChatgptSignInCompletePostResponseObject, error) {
	done, err := s.svc.FinishChatGPTSignIn(ctx, r.ConfigId)
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
