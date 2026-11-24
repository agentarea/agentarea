package service

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/store"
)

const consumerType = "provider_config"

// ConfigView is a configuration with what its response carries of its spec and instances.
type ConfigView struct {
	domain.Config
	Spec *catalogapi.ProviderSpec
	// ModelSpecIDs are the model_spec_id of every instance on the configuration (model_instance_ids).
	ModelSpecIDs []string
}

func (s *Service) views(ctx context.Context, sess db.Session, ws scope.Workspace, cs []domain.Config) ([]ConfigView, error) {
	ids := make([]uuid.UUID, 0, len(cs))
	specIDs := make([]uuid.UUID, 0, len(cs))
	for _, c := range cs {
		ids = append(ids, uuid.MustParse(c.ID))
		specIDs = append(specIDs, uuid.MustParse(c.ProviderSpecID))
	}
	inst, err := s.st.InstanceSpecIDs(ctx, sess, ids)
	if err != nil {
		return nil, err
	}
	specs, err := s.d.Catalog.ProviderSpecs(ctx, ws, specIDs)
	if err != nil {
		return nil, err
	}
	out := make([]ConfigView, len(cs))
	for i, c := range cs {
		v := ConfigView{Config: c, ModelSpecIDs: inst[c.ID]}
		if v.ModelSpecIDs == nil {
			v.ModelSpecIDs = []string{}
		}
		if sp, ok := specs[uuid.MustParse(c.ProviderSpecID)]; ok {
			v.Spec = &sp
		}
		out[i] = v
	}
	return out, nil
}

func (s *Service) view(ctx context.Context, ws scope.Workspace, id uuid.UUID) (ConfigView, bool, error) {
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return ConfigView{}, false, err
	}
	defer release()
	c, ok, err := s.st.Config(ctx, sess, id)
	if err != nil || !ok {
		return ConfigView{}, ok, err
	}
	vs, err := s.views(ctx, sess, ws, []domain.Config{c})
	if err != nil {
		return ConfigView{}, false, err
	}
	return vs[0], true, nil
}

// Config is get_provider_config: the workspace's own or the platform's.
func (s *Service) Config(ctx context.Context, id uuid.UUID) (ConfigView, bool, error) {
	ws, _, err := caller(ctx)
	if err != nil {
		return ConfigView{}, false, err
	}
	return s.view(ctx, ws, id)
}

// Configs is list_provider_configs.
func (s *Service) Configs(ctx context.Context, f store.ConfigFilter) ([]ConfigView, error) {
	ws, _, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return nil, err
	}
	defer release()
	cs, err := s.st.Configs(ctx, sess, f)
	if err != nil {
		return nil, err
	}
	return s.views(ctx, sess, ws, cs)
}

// assertEndpointAllowed is assert_endpoint_allowed: one answer whether private or unresolvable.
func (s *Service) assertEndpointAllowed(ctx context.Context, endpoint string) error {
	if _, err := s.d.Out.Guard().CheckURL(ctx, endpoint); err != nil {
		slog.InfoContext(ctx, "Refused provider endpoint_url on save", "error", err)
		return &BadRequestError{Detail: EndpointNotAllowed}
	}
	return nil
}

// requireUsableSecret is _require_usable_secret.
func (s *Service) requireUsableSecret(ctx context.Context, sess db.Session, id string) (ksecrets.Secret, error) {
	sec, ok, err := s.d.Secrets.Secret(ctx, sess, id)
	if err != nil {
		return ksecrets.Secret{}, err
	}
	if !ok {
		return ksecrets.Secret{}, &NotFoundError{Detail: fmt.Sprintf("No secret %s in this workspace", id)}
	}
	if sec.OwnerType != nil {
		return ksecrets.Secret{}, &BadRequestError{Detail: fmt.Sprintf(
			"Secret '%s' is managed by %s and cannot be reused as a provider API key.", sec.Name, *sec.OwnerType)}
	}
	return sec, nil
}

func (s *Service) secretIDFor(ctx context.Context, sess db.Session, name string) (*string, error) {
	sec, ok, err := s.d.Secrets.SecretNamed(ctx, sess, name)
	if err != nil || !ok {
		return nil, err
	}
	return &sec.ID, nil
}

// registerReference is _register_reference.
func (s *Service) registerReference(ctx context.Context, sess db.Session, c domain.Config) error {
	var refs []ksecrets.Reference
	if c.APIKeySecretID != nil {
		refs = []ksecrets.Reference{{SecretID: *c.APIKeySecretID, Field: "api_key"}}
	}
	return s.d.Secrets.StageReferences(ctx, sess, consumerType, c.ID, refs)
}

func ownSecretIfHeld(c domain.Config) string {
	own := domain.OwnSecretName(c.ID)
	if c.APIKey != nil && *c.APIKey == own {
		return own
	}
	return ""
}

// CreateConfig is create_provider_config.
func (s *Service) CreateConfig(ctx context.Context, n domain.NewConfig) (ConfigView, error) {
	ws, userID, err := caller(ctx)
	if err != nil {
		return ConfigView{}, err
	}
	if err := s.admin(ctx); err != nil {
		return ConfigView{}, err
	}
	specID, err := uuid.Parse(n.ProviderSpecID)
	if err != nil {
		return ConfigView{}, err
	}
	spec, ok, err := s.d.Catalog.ProviderSpec(ctx, ws, specID)
	if err != nil {
		return ConfigView{}, err
	} else if !ok {
		return ConfigView{}, &NotFoundError{Detail: "Provider spec not found"}
	}
	if n.EndpointURL != nil && *n.EndpointURL != "" && signsIn(spec.Auth) {
		return ConfigView{}, noEndpointForChatGPT()
	}
	if n.EndpointURL != nil && *n.EndpointURL != "" {
		if err := s.assertEndpointAllowed(ctx, *n.EndpointURL); err != nil {
			return ConfigView{}, err
		}
	}
	id := uuid.New()
	c := domain.Config{
		ID: id.String(), ProviderSpecID: specID.String(), Name: n.Name, Description: n.Description,
		EndpointURL: n.EndpointURL, IsActive: true, IsPublic: n.IsPublic, WorkspaceID: ws.ID(), CreatedBy: userID,
	}
	err = s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		switch {
		case n.APIKeySecretID != nil:
			sec, err := s.requireUsableSecret(ctx, sess, *n.APIKeySecretID)
			if err != nil {
				return err
			}
			c.APIKey, c.APIKeySecretID = &sec.Name, &sec.ID
		case n.APIKey != nil:
			name := domain.OwnSecretName(c.ID)
			if err := s.d.Secrets.Manager(sess, userID).Set(ctx, name, *n.APIKey); err != nil {
				return err
			}
			c.APIKey = &name
			if c.APIKeySecretID, err = s.secretIDFor(ctx, sess, name); err != nil {
				return err
			}
		}
		if err := s.registerReference(ctx, sess, c); err != nil {
			return err
		}
		return s.st.InsertConfig(ctx, sess, c, s.d.Now())
	})
	if err != nil {
		return ConfigView{}, err
	}
	v, _, err := s.view(ctx, ws, id)
	return v, err
}

// UpdateConfig is update_provider_config (PUT and PATCH alike); false when not found.
func (s *Service) UpdateConfig(ctx context.Context, id uuid.UUID, p domain.ConfigPatch) (ConfigView, bool, error) {
	ws, userID, err := caller(ctx)
	if err != nil {
		return ConfigView{}, false, err
	}
	if err := s.admin(ctx); err != nil {
		return ConfigView{}, false, err
	}
	found := false
	err = s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		c, ok, err := s.st.Config(ctx, sess, id)
		if err != nil || !ok {
			return err
		}
		if c.PlatformManaged() {
			return &PlatformManagedError{Name: c.Name, Verb: "modified"}
		}
		if p.Name.Value != nil {
			c.Name = *p.Name.Value
		}
		if p.Description.Set {
			c.Description = p.Description.Value
		}
		if p.EndpointURL.Set {
			if p.EndpointURL.Value != nil && *p.EndpointURL.Value != "" {
				specID, err := uuid.Parse(c.ProviderSpecID)
				if err != nil {
					return err
				}
				spec, ok, err := s.d.Catalog.ProviderSpec(ctx, ws, specID)
				if err != nil {
					return err
				}
				if ok && signsIn(spec.Auth) {
					return noEndpointForChatGPT()
				}
				if err := s.assertEndpointAllowed(ctx, *p.EndpointURL.Value); err != nil {
					return err
				}
			}
			c.EndpointURL = p.EndpointURL.Value
		}
		if p.IsActive.Value != nil {
			c.IsActive = *p.IsActive.Value
		}
		if p.IsPublic.Value != nil {
			c.IsPublic = *p.IsPublic.Value
		}
		stale := ""
		switch {
		case p.APIKeySecretID.Value != nil:
			sec, err := s.requireUsableSecret(ctx, sess, *p.APIKeySecretID.Value)
			if err != nil {
				return err
			}
			stale = ownSecretIfHeld(c)
			c.APIKey, c.APIKeySecretID = &sec.Name, &sec.ID
		case p.APIKey.Set:
			name := domain.OwnSecretName(c.ID)
			if p.APIKey.Value != nil {
				if err := s.d.Secrets.Manager(sess, userID).Set(ctx, name, *p.APIKey.Value); err != nil {
					return err
				}
				c.APIKey = &name
				if c.APIKeySecretID, err = s.secretIDFor(ctx, sess, name); err != nil {
					return err
				}
			} else {
				stale = ownSecretIfHeld(c)
				c.APIKey, c.APIKeySecretID = nil, nil
			}
		}
		if p.APIKey.Set || p.APIKeySecretID.Set {
			if err := s.registerReference(ctx, sess, c); err != nil {
				return err
			}
		}
		if found, err = s.st.UpdateConfig(ctx, sess, c, s.d.Now()); err != nil || !found {
			return err
		}
		if stale != "" {
			if _, err := s.d.Secrets.Manager(sess, userID).Delete(ctx, stale); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil || !found {
		return ConfigView{}, false, err
	}
	return s.view(ctx, ws, id)
}

// DeleteConfig is delete_provider_config; false when not found.
func (s *Service) DeleteConfig(ctx context.Context, id uuid.UUID) (bool, error) {
	ws, userID, err := caller(ctx)
	if err != nil {
		return false, err
	}
	if err := s.admin(ctx); err != nil {
		return false, err
	}
	deleted := false
	err = s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		c, ok, err := s.st.Config(ctx, sess, id)
		if err != nil {
			return err
		}
		own := ""
		if ok {
			if c.PlatformManaged() {
				return &PlatformManagedError{Name: c.Name, Verb: "deleted"}
			}
			own = ownSecretIfHeld(c)
		}
		if err := s.d.Secrets.StageReferences(ctx, sess, consumerType, id.String(), nil); err != nil {
			return err
		}
		if deleted, err = s.st.DeleteConfig(ctx, sess, id); err != nil {
			return err
		}
		if deleted && own != "" {
			_, err = s.d.Secrets.Manager(sess, userID).Delete(ctx, own)
		}
		return err
	})
	return deleted, err
}
