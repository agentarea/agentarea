package handlers

import (
	"context"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/service"
)

func TestProviderConfigWritesRefuseMembersWithPythonsDetail(t *testing.T) {
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	c := authn.Caller{Principal: authn.Principal{UserID: "member"}, Workspace: ws}
	tools := ProvidersToolset{Svc: service.New(service.Deps{Admin: func(context.Context) error { return authz.ErrNotWorkspaceAdmin }})}
	_, err = tools.CreateConfig(context.Background(), c, api.NewProviderConfig{ProviderSpecID: uuid.NewString(), Name: "Main", APIKey: "sk"})
	if err == nil || err.Error() != authz.NotAdminDetail {
		t.Fatalf("create: %v", err)
	}
	if _, err := tools.DeleteConfig(context.Background(), c, uuid.NewString()); err == nil || err.Error() != authz.NotAdminDetail {
		t.Fatalf("delete: %v", err)
	}
	if err := refusal(authz.ErrDenied); err.Error() != "Permission denied" {
		t.Fatalf("denied: %v", err)
	}
}
