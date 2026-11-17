package app

import (
	"context"
	"errors"

	kscope "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	agentsservice "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/service"
)

// delegateSecrets finds the workspace secret a remote delegate is bound to in the secret catalog.
type delegateSecrets struct{ d coreDeps }

var _ agentsservice.DelegateSecrets = delegateSecrets{}

func (s delegateSecrets) SecretNamed(ctx context.Context, ws kscope.Workspace, name string) (ksecrets.Secret, bool, error) {
	secret, err := s.d.secretCatalog(nil, ws, ksecrets.Actor{}).GetByName(ctx, name)
	if errors.Is(err, ksecrets.ErrNotFound) {
		return ksecrets.Secret{}, false, nil
	}
	return secret, err == nil, err
}
