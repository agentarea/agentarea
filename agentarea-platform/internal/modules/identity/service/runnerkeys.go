package service

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/store"
)

// RunnerKeys is APIKeyService for clients' runners (create_token/list_tokens with
// client_id, get_token, revoke_token); the caller audits.
type RunnerKeys struct{ S *Service }

var _ api.RunnerKeys = RunnerKeys{}

func runnerKey(k domain.APIKey) api.RunnerKey {
	return api.RunnerKey{ID: k.ID, Name: k.Name, Prefix: k.TokenPrefix, CreatedBy: k.CreatedBy, CreatedAt: k.CreatedAt,
		LastUsedAt: k.LastAccessedAt, ClientID: k.ClientID, Active: k.IsActive}
}

func (r RunnerKeys) Issue(ctx context.Context, c authn.Caller, clientID, name string) (api.RunnerKey, string, error) {
	client, err := uuid.Parse(clientID)
	if err != nil {
		return api.RunnerKey{}, "", err
	}
	token, prefix, hash, err := authn.NewAPIKey()
	if err != nil {
		return api.RunnerKey{}, "", r.S.keyFailed(ctx, err)
	}
	k := store.NewAPIKey{ID: uuid.New(), CreatedBy: c.UserID, Name: name, TokenHash: hash, TokenPrefix: prefix, ClientID: &client}
	var created domain.APIKey
	err = r.S.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		var err error
		created, err = r.S.d.Store.InsertAPIKey(ctx, sess, k, r.S.local())
		return err
	})
	if err != nil {
		return api.RunnerKey{}, "", r.S.keyFailed(ctx, err)
	}
	return runnerKey(created), token, nil
}

func (r RunnerKeys) List(ctx context.Context, c authn.Caller, clientID string) ([]api.RunnerKey, error) {
	client, err := uuid.Parse(clientID)
	if err != nil {
		return nil, err
	}
	sess, release, err := r.S.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return nil, err
	}
	defer release()
	keys, err := r.S.d.Store.ListClientAPIKeys(ctx, sess, client)
	if err != nil {
		return nil, err
	}
	out := make([]api.RunnerKey, 0, len(keys))
	for _, k := range keys {
		out = append(out, runnerKey(k))
	}
	return out, nil
}

func (r RunnerKeys) Get(ctx context.Context, c authn.Caller, keyID string) (api.RunnerKey, bool, error) {
	id, err := uuid.Parse(keyID)
	if err != nil {
		return api.RunnerKey{}, false, nil
	}
	sess, release, err := r.S.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return api.RunnerKey{}, false, err
	}
	defer release()
	k, ok, err := r.S.d.Store.APIKeyByID(ctx, sess, id)
	if err != nil || !ok {
		return api.RunnerKey{}, false, err
	}
	return runnerKey(k), true, nil
}

func (r RunnerKeys) Revoke(ctx context.Context, c authn.Caller, keyID string) error {
	id, err := uuid.Parse(keyID)
	if err != nil {
		return domain.ErrAPIKeyNotFound
	}
	return r.S.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		return r.S.d.Store.DeactivateAPIKey(ctx, sess, id, r.S.local())
	})
}
