package service

import (
	"context"
	"encoding/json"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
)

// ListAuthConfigs is every auth config of the caller's workspace.
func (s *Service) ListAuthConfigs(ctx context.Context, c authn.Caller) ([]domain.AuthConfig, error) {
	var out []domain.AuthConfig
	err := s.read(ctx, c, func(sess db.Session) (err error) {
		out, err = s.d.Auth.List(ctx, sess)
		return err
	})
	return out, err
}

// GetAuthConfig is the auth config id, 404 when the workspace has none.
func (s *Service) GetAuthConfig(ctx context.Context, c authn.Caller, id uuid.UUID) (domain.AuthConfig, error) {
	var out domain.AuthConfig
	err := s.read(ctx, c, func(sess db.Session) error {
		a, ok, err := s.d.Auth.Get(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return &domain.NotFound{Msg: "MCP auth config not found"}
		}
		out = a
		return nil
	})
	return out, err
}

// CreateAuthConfig writes the config and its credentials, which the secret
// store keeps under the config's own name.
func (s *Service) CreateAuthConfig(ctx context.Context, c authn.Caller, n domain.AuthConfigNew) (domain.AuthConfig, error) {
	if err := domain.CheckCreate(n); err != nil {
		return domain.AuthConfig{}, err
	}
	var out domain.AuthConfig
	err := s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		id := s.d.NewID()
		a, err := s.d.Auth.Insert(ctx, sess, id, c.UserID, n, s.d.Now())
		if err != nil {
			return err
		}
		if len(n.Credentials) > 0 {
			key, err := s.storeCredentials(ctx, sess, c, id.String(), n.Credentials)
			if err != nil {
				return err
			}
			if err := s.d.Auth.SetSecretKey(ctx, sess, id, key, s.d.Now()); err != nil {
				return err
			}
			a.SecretKey = &key
		}
		out = a
		return nil
	})
	return out, err
}

// UpdateAuthConfig changes the fields given and, when credentials are given,
// rotates them. A catalog-owned config changes only by reconnecting.
func (s *Service) UpdateAuthConfig(ctx context.Context, c authn.Caller, id uuid.UUID, p domain.AuthConfigPatch) (domain.AuthConfig, error) {
	var out domain.AuthConfig
	err := s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		existing, ok, err := s.d.Auth.Get(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return &domain.NotFound{Msg: "MCP auth config not found"}
		}
		if err := domain.CheckUpdate(existing.Config, p); err != nil {
			return err
		}
		if p.Name != nil || p.Description != nil || p.Config != nil {
			if err := s.d.Auth.Update(ctx, sess, id, p.Name, p.Description, p.Config, s.d.Now()); err != nil {
				return err
			}
		}
		if p.Credentials != nil {
			key, err := s.storeCredentials(ctx, sess, c, id.String(), p.Credentials)
			if err != nil {
				return err
			}
			if err := s.d.Auth.SetSecretKey(ctx, sess, id, key, s.d.Now()); err != nil {
				return err
			}
		}
		updated, ok, err := s.d.Auth.Get(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return &domain.NotFound{Msg: "MCP auth config not found"}
		}
		out = updated
		return nil
	})
	return out, err
}

// DeleteAuthConfig refuses a config a connection still uses, deletes its
// credentials and row, then clears the secret references it held.
func (s *Service) DeleteAuthConfig(ctx context.Context, c authn.Caller, id uuid.UUID) error {
	err := s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		insts, err := s.d.Auth.LinkedInstances(ctx, sess, id)
		if err != nil {
			return err
		}
		conns, err := s.d.Auth.LinkedConnections(ctx, sess, id)
		if err != nil {
			return err
		}
		if len(insts)+len(conns) > 0 {
			return &domain.Linked{Msg: domain.LinkedMessage(id.String(), append(insts, conns...))}
		}
		existing, ok, err := s.d.Auth.Get(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return &domain.NotFound{Msg: "MCP auth config not found"}
		}
		if existing.SecretKey != nil {
			if _, err := s.d.Secrets.Manager(sess, c.UserID).Delete(ctx, *existing.SecretKey); err != nil {
				return err
			}
		}
		_, err = s.d.Auth.Delete(ctx, sess, id)
		return err
	})
	if err != nil {
		return err
	}
	return s.d.Catalog(c.Workspace, actor(c)).ClearReferences(ctx, "mcp_auth_config", id.String())
}

// storeCredentials writes the credentials JSON under the config's secret name.
func (s *Service) storeCredentials(ctx context.Context, sess db.Session, c authn.Caller, configID string, creds map[string]any) (string, error) {
	raw, err := json.Marshal(creds)
	if err != nil {
		return "", err
	}
	key := domain.SecretKeyFor(configID)
	if err := s.d.Secrets.Manager(sess, c.UserID).Set(ctx, key, string(raw)); err != nil {
		return "", err
	}
	return key, nil
}
