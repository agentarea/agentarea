package service

import (
	"context"
	"errors"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
)

// A connection the platform manages is in no workspace's graph: attaching it is
// allowed without a grant, while a foreign personal one is still refused.
func TestAttachingAPlatformConnectionNeedsNoGrant(t *testing.T) {
	platform, foreign := uuid.NewString(), uuid.NewString()
	ws, err := scope.NewWorkspace(uuid.NewString(), "w")
	if err != nil {
		t.Fatal(err)
	}
	c := authn.Caller{Principal: authn.Principal{UserID: "u1"}, Workspace: ws}
	s := New(Deps{Graph: &clientFakeGraph{objects: map[string]bool{}},
		Attachable: clientFakeConnections{names: map[string]string{platform: "platform", foreign: "someone's"}}})
	openapi := func(id string) domain.Tool {
		return domain.Tool{Type: domain.ToolOpenAPI, Name: "checko", Settings: &domain.Settings{OpenAPIConnectionID: &id}}
	}

	if err := s.requireUsable(context.Background(), c, []domain.Tool{openapi(platform), {Type: domain.ToolMCP, Name: platform}}, nil); err != nil {
		t.Fatalf("platform connection refused: %v", err)
	}
	var perm *PermissionError
	if err := s.requireUsable(context.Background(), c, []domain.Tool{openapi(foreign)}, nil); !errors.As(err, &perm) {
		t.Fatalf("foreign connection allowed: %v", err)
	}
}
