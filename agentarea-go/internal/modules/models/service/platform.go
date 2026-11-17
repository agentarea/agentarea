package service

import (
	"context"
	"errors"
	"log/slog"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/store"
)

const platformPrincipal = "platform"

var _ api.DeclaredProviders = (*Service)(nil)

// DeclareProvider writes the key, the configuration and its instances in one transaction. A key
// that already decrypts to the same value is left alone.
func (s *Service) DeclareProvider(ctx context.Context, d api.ProviderDeclaration) error {
	ws, err := scope.NewWorkspace(d.WorkspaceID, "")
	if err != nil {
		return err
	}
	return s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		name := domain.OwnSecretName(d.ConfigID.String())
		if err := putSecret(ctx, s.d.Secrets.Manager(sess, platformPrincipal), name, d.APIKey); err != nil {
			return err
		}
		sec, ok, err := s.d.Secrets.SecretNamed(ctx, sess, name)
		if err != nil {
			return err
		}
		if !ok {
			return errors.New("the provider key was stored but its secret row is missing")
		}
		now := s.d.Now()
		if err := (store.Platform{}).DeclareConfig(ctx, sess, d, name, sec.ID, platformPrincipal, now); err != nil {
			return err
		}
		for _, in := range d.Instances {
			if err := (store.Platform{}).DeclareInstance(ctx, sess, d.ConfigID, in, platformPrincipal, now); err != nil {
				return err
			}
		}
		return nil
	})
}

// PlatformDefaults implements api.DeclaredProviders.
func (s *Service) PlatformDefaults(ctx context.Context) ([]string, error) {
	q, release, err := s.d.DB.Global().Read(ctx)
	if err != nil {
		return nil, err
	}
	defer release()
	return store.Platform{}.PlatformDefaults(ctx, q)
}

// putSecret sets name to value unless it already holds it; a value the key cannot open is rewritten.
func putSecret(ctx context.Context, m ksecrets.Manager, name, value string) error {
	current, err := m.Get(ctx, name)
	switch {
	case err == nil && current == value:
		return nil
	case errors.Is(err, ksecrets.ErrDecrypt):
		slog.WarnContext(ctx, "A declared secret does not decrypt with the current key; rewriting it", "secret_name", name)
	case err != nil && !errors.Is(err, ksecrets.ErrNotFound):
		return err
	}
	return m.Set(ctx, name, value)
}
