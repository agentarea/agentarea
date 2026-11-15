package service

import (
	"context"
	"slices"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
)

// SecretView is a secret with what the response shows beside it.
type SecretView struct {
	Secret    secrets.Secret
	UsedBy    []secrets.ConsumerRef
	OwnerName *string
}

// HiddenSecretError is a managed secret of an owner type no page surfaces.
type HiddenSecretError struct{ ID string }

func (e *HiddenSecretError) Error() string { return "No secret " + e.ID + " in this workspace" }

// SecretsMounted reports whether the secrets profile was passed in.
func (sv *Service) SecretsMounted() bool { return sv.d.Secrets != nil && sv.d.Owners != nil }

func (sv *Service) catalog(c authn.Caller) secrets.Catalog {
	return sv.d.Secrets(c.Workspace, secrets.Actor{UserID: c.UserID, GraphSubject: c.GraphSubject()}, secretAuditor{sv: sv, c: c})
}

func (sv *Service) ownerNames(ctx context.Context, c authn.Caller, owners []OwnerRef) (map[OwnerRef]string, error) {
	if len(owners) == 0 {
		return map[OwnerRef]string{}, nil
	}
	var out map[OwnerRef]string
	err := sv.read(ctx, c.Workspace, func(s db.Session) (err error) {
		out, err = sv.d.Owners(ctx, s, owners)
		return err
	})
	return out, err
}

func (sv *Service) view(ctx context.Context, cat secrets.Catalog, sec secrets.Secret, names map[OwnerRef]string) (SecretView, error) {
	v := SecretView{Secret: sec, UsedBy: []secrets.ConsumerRef{}}
	if sec.OwnerType == nil {
		used, err := cat.Consumers(ctx, sec.ID)
		if err != nil {
			return SecretView{}, err
		}
		v.UsedBy = used
	}
	if sec.OwnerType != nil && sec.OwnerID != nil {
		if n, ok := names[OwnerRef{Type: *sec.OwnerType, ID: *sec.OwnerID}]; ok {
			v.OwnerName = &n
		}
	}
	return v, nil
}

// ListSecrets is the caller's own secrets and the surfaced managed ones.
func (sv *Service) ListSecrets(ctx context.Context, c authn.Caller) ([]SecretView, error) {
	cat := sv.catalog(c)
	list, err := cat.ListVisible(ctx)
	if err != nil {
		return nil, err
	}
	var owners []OwnerRef
	for _, s := range list {
		if s.OwnerType != nil && *s.OwnerType != "" && s.OwnerID != nil && *s.OwnerID != "" {
			owners = append(owners, OwnerRef{Type: *s.OwnerType, ID: *s.OwnerID})
		}
	}
	names, err := sv.ownerNames(ctx, c, owners)
	if err != nil {
		return nil, err
	}
	out := make([]SecretView, 0, len(list))
	for _, s := range list {
		v, err := sv.view(ctx, cat, s, names)
		if err != nil {
			return nil, err
		}
		out = append(out, v)
	}
	return out, nil
}

// GetSecret is one secret's metadata, user-owned or surfaced.
func (sv *Service) GetSecret(ctx context.Context, c authn.Caller, id string) (SecretView, error) {
	cat := sv.catalog(c)
	sec, err := cat.Get(ctx, id)
	if err != nil {
		return SecretView{}, err
	}
	if sec.OwnerType != nil && !slices.Contains(secrets.SurfacedOwnerTypes(), *sec.OwnerType) {
		return SecretView{}, &HiddenSecretError{ID: id}
	}
	var names map[OwnerRef]string
	if sec.OwnerType != nil && *sec.OwnerType != "" && sec.OwnerID != nil && *sec.OwnerID != "" {
		if names, err = sv.ownerNames(ctx, c, []OwnerRef{{Type: *sec.OwnerType, ID: *sec.OwnerID}}); err != nil {
			return SecretView{}, err
		}
	}
	return sv.view(ctx, cat, sec, names)
}

// CreateSecret stores a user secret; it has no consumers yet.
func (sv *Service) CreateSecret(ctx context.Context, c authn.Caller, name, value string, description *string) (SecretView, error) {
	sec, err := sv.catalog(c).CreateUser(ctx, name, value, description)
	if err != nil {
		return SecretView{}, err
	}
	return SecretView{Secret: sec, UsedBy: []secrets.ConsumerRef{}}, nil
}

func (sv *Service) withConsumers(ctx context.Context, cat secrets.Catalog, sec secrets.Secret) (SecretView, error) {
	used, err := cat.Consumers(ctx, sec.ID)
	if err != nil {
		return SecretView{}, err
	}
	return SecretView{Secret: sec, UsedBy: used}, nil
}

// UpdateSecretDescription sets a user secret's description.
func (sv *Service) UpdateSecretDescription(ctx context.Context, c authn.Caller, id string, description *string) (SecretView, error) {
	cat := sv.catalog(c)
	sec, err := cat.UpdateDescription(ctx, id, description)
	if err != nil {
		return SecretView{}, err
	}
	return sv.withConsumers(ctx, cat, sec)
}

// RotateSecret replaces a user secret's value.
func (sv *Service) RotateSecret(ctx context.Context, c authn.Caller, id, value string) (SecretView, error) {
	cat := sv.catalog(c)
	sec, err := cat.RotateUser(ctx, id, value)
	if err != nil {
		return SecretView{}, err
	}
	return sv.withConsumers(ctx, cat, sec)
}

// DeleteSecret removes a user secret nothing uses.
func (sv *Service) DeleteSecret(ctx context.Context, c authn.Caller, id string) error {
	return sv.catalog(c).DeleteUser(ctx, id)
}
