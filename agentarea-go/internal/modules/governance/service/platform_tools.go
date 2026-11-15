package service

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
)

// ListOwnSecrets is list_user_secrets: the caller's own secrets, none managed.
func (sv *Service) ListOwnSecrets(ctx context.Context, c authn.Caller) ([]secrets.Secret, error) {
	return sv.catalog(c).ListUser(ctx)
}

// DeleteSecretByName is get_by_name then delete_user_secret.
func (sv *Service) DeleteSecretByName(ctx context.Context, c authn.Caller, name string) error {
	cat := sv.catalog(c)
	sec, err := cat.GetByName(ctx, name)
	if err != nil {
		return err
	}
	return cat.DeleteUser(ctx, sec.ID)
}

// TaskSnapshotsWired reports whether runs' task metadata reader was passed in.
func (sv *Service) TaskSnapshotsWired() bool { return sv.d.Tasks != nil }
