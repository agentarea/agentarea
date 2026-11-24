package store

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/domain"
)

// PutSignIn keeps a member's pending ChatGPT sign-in on a configuration, replacing an older one.
func (Store) PutSignIn(ctx context.Context, s db.Session, in domain.SignIn) error {
	id, err := uuid.Parse(in.ConfigID)
	if err != nil {
		return err
	}
	return New(s.Q()).PutSignIn(ctx, PutSignInParams{
		ProviderConfigID: id, UserID: in.UserID, WorkspaceID: s.Workspace().ID(),
		DeviceAuthID: in.DeviceAuthID, UserCode: in.UserCode, ExpiresAt: naive(in.ExpiresAt),
	})
}

// SignIn is the member's pending sign-in on the configuration; false when there is none.
func (Store) SignIn(ctx context.Context, s db.Session, configID uuid.UUID, userID string) (domain.SignIn, bool, error) {
	r, err := New(s.Q()).GetSignIn(ctx, GetSignInParams{ProviderConfigID: configID, UserID: userID, WorkspaceID: s.Workspace().ID()})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.SignIn{}, false, nil
	}
	if err != nil {
		return domain.SignIn{}, false, err
	}
	return domain.SignIn{ConfigID: configID.String(), UserID: userID, DeviceAuthID: r.DeviceAuthID, UserCode: r.UserCode,
		ExpiresAt: r.ExpiresAt.Time}, true, nil
}

// DeleteSignIn drops the member's pending sign-in on the configuration.
func (Store) DeleteSignIn(ctx context.Context, s db.Session, configID uuid.UUID, userID string) error {
	return New(s.Q()).DeleteSignIn(ctx, DeleteSignInParams{ProviderConfigID: configID, UserID: userID, WorkspaceID: s.Workspace().ID()})
}
