package service

import (
	"context"
	"errors"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
)

type namedSecrets map[string]ksecrets.Secret

func (n namedSecrets) SecretNamed(_ context.Context, _ scope.Workspace, name string) (ksecrets.Secret, bool, error) {
	s, ok := n[name]
	return s, ok, nil
}

func remoteDelegate(secret string) domain.Tool {
	url := "https://docs.test/a2a"
	st := &domain.Settings{A2AURL: &url}
	if secret != "" {
		st.AuthSecretName = &secret
	}
	return domain.Tool{Type: domain.ToolAgent, Name: "docs-writer", Settings: st}
}

func delegateService(admin error) *Service {
	managed := "connection"
	return New(Deps{
		Admin: func(context.Context) error { return admin },
		Secrets: namedSecrets{
			"docs-team-key":  {Name: "docs-team-key"},
			"oauth-token": {Name: "oauth-token", OwnerType: &managed},
		},
	})
}

func TestBindingASecretToARemoteDelegate(t *testing.T) {
	ctx := context.Background()
	ws, err := scope.NewWorkspace(uuid.NewString(), "")
	if err != nil {
		t.Fatal(err)
	}
	if err := delegateService(nil).validateDelegates(ctx, ws, []domain.Tool{remoteDelegate("docs-team-key")}, nil); err != nil {
		t.Fatalf("an admin binds a workspace secret: %v", err)
	}
	if err := delegateService(authz.ErrNotWorkspaceAdmin).validateDelegates(ctx, ws, []domain.Tool{remoteDelegate("")}, nil); err != nil {
		t.Fatalf("a member adds a remote delegate without a secret: %v", err)
	}
	var perm *PermissionError
	err = delegateService(authz.ErrNotWorkspaceAdmin).validateDelegates(ctx, ws, []domain.Tool{remoteDelegate("docs-team-key")}, nil)
	if !errors.As(err, &perm) || perm.Msg != "Only a workspace admin may send a workspace secret to a remote delegate." {
		t.Fatalf("a member binds a secret: %v", err)
	}
	previous := []domain.Tool{remoteDelegate("docs-team-key")}
	if err := delegateService(authz.ErrNotWorkspaceAdmin).validateDelegates(ctx, ws, []domain.Tool{remoteDelegate("docs-team-key")}, previous); err != nil {
		t.Fatalf("a member keeps a bound secret: %v", err)
	}
	down := errors.New("graph down")
	if err := delegateService(down).validateDelegates(ctx, ws, []domain.Tool{remoteDelegate("docs-team-key")}, nil); !errors.Is(err, down) {
		t.Fatalf("an unanswered admin check = %v", err)
	}
	var invalid *domain.InvalidError
	err = delegateService(nil).validateDelegates(ctx, ws, []domain.Tool{remoteDelegate("missing")}, nil)
	if !errors.As(err, &invalid) || invalid.Code != domain.CodeInvalidDelegate ||
		invalid.Detail != "Delegate 'docs-writer': no secret named 'missing' in this workspace." {
		t.Fatalf("a missing secret = %v", err)
	}
	err = delegateService(nil).validateDelegates(ctx, ws, []domain.Tool{remoteDelegate("oauth-token")}, nil)
	if !errors.As(err, &invalid) ||
		invalid.Detail != "Delegate 'docs-writer': secret 'oauth-token' is managed by connection and cannot be sent to a remote agent." {
		t.Fatalf("a managed secret = %v", err)
	}
}
