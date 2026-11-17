package service

import (
	"context"
	"errors"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/domain"
)

// Registry secret consumer (registry_credentials.py).
const (
	RegistrySecretConsumer = "registry"
	RegistrySecretField    = "credentials"
)

// ErrNoSecrets: a workspace-registry write was reached with no secret catalog.
var ErrNoSecrets = errors.New("catalog: workspace-registry writes need the secret catalog")

func (s *Service) secrets(c authn.Caller) (SecretUse, error) {
	if s.d.Secrets == nil {
		return nil, ErrNoSecrets
	}
	return s.d.Secrets(c.Workspace, ksecrets.Actor{UserID: c.UserID, GraphSubject: c.GraphSubject()}), nil
}

// usableSecret is _usable_secret: 404 for a missing secret, 403 for one
// the platform manages or the caller may not use.
func usableSecret(ctx context.Context, sec SecretUse, id string) (string, error) {
	got, err := sec.GetForUse(ctx, id)
	switch {
	case errors.Is(err, ksecrets.ErrNotFound):
		return "", &NotFoundError{Detail: err.Error()}
	case errors.Is(err, ksecrets.ErrManaged), errors.Is(err, ksecrets.ErrAccessDenied):
		return "", &ForbiddenError{Detail: err.Error()}
	case err != nil:
		return "", err
	}
	return got.ID, nil
}

// CreateWorkspaceRegistry is create_workspace_registry: n carries the
// caller's workspace and scope; credentials, when given, must be usable.
func (s *Service) CreateWorkspaceRegistry(ctx context.Context, c authn.Caller, n domain.NewRegistry) (domain.Registry, error) {
	sec, err := s.secrets(c)
	if err != nil {
		return domain.Registry{}, err
	}
	if n.CredentialsSecretRef != nil {
		id, err := usableSecret(ctx, sec, *n.CredentialsSecretRef)
		if err != nil {
			return domain.Registry{}, err
		}
		n.CredentialsSecretRef = &id
	}
	r, err := s.CreateRegistry(ctx, c.Workspace, n, nil)
	if integrityError(err) {
		return domain.Registry{}, &ConflictError{Detail: "This workspace already has a registry named " + PyRepr(n.Name)}
	}
	if err != nil {
		return domain.Registry{}, err
	}
	if r.CredentialsSecretRef != nil {
		if err := sec.AddReference(ctx, *r.CredentialsSecretRef, RegistrySecretConsumer, r.ID, RegistrySecretField); err != nil {
			return domain.Registry{}, err
		}
	}
	return r, nil
}

// UpdateWorkspaceRegistry is update_workspace_registry on current, one of
// the caller's workspace's own; references follow a credentials change.
func (s *Service) UpdateWorkspaceRegistry(ctx context.Context, c authn.Caller, current domain.Registry, p domain.RegistryPatch) (domain.Registry, error) {
	sec, err := s.secrets(c)
	if err != nil {
		return domain.Registry{}, err
	}
	if p.CredentialsSecretRef.Set && p.CredentialsSecretRef.Value != nil {
		id, err := usableSecret(ctx, sec, *p.CredentialsSecretRef.Value)
		if err != nil {
			return domain.Registry{}, err
		}
		p.CredentialsSecretRef.Value = &id
	}
	if (p.Name.Set && p.Name.Value == nil) || (p.IsActive.Set && p.IsActive.Value == nil) {
		if err := s.validatePatch(ctx, current, p); err != nil {
			return domain.Registry{}, err
		}
		return domain.Registry{}, &ConflictError{Detail: "A registry with that name exists"}
	}
	r, err := s.UpdateRegistry(ctx, c.Workspace, current, p)
	if integrityError(err) {
		return domain.Registry{}, &ConflictError{Detail: "A registry with that name exists"}
	}
	if err != nil {
		return domain.Registry{}, err
	}
	if p.CredentialsSecretRef.Set {
		if err := sec.ClearReferences(ctx, RegistrySecretConsumer, r.ID); err != nil {
			return domain.Registry{}, err
		}
		if r.CredentialsSecretRef != nil {
			if err := sec.AddReference(ctx, *r.CredentialsSecretRef, RegistrySecretConsumer, r.ID, RegistrySecretField); err != nil {
				return domain.Registry{}, err
			}
		}
	}
	return r, nil
}
