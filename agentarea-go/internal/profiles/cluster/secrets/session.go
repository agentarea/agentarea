package secrets

import (
	"context"
	"errors"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	kernel "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
)

// Session is the secret rows of the session's workspace, read and referenced
// inside the caller's transaction, so a secret the transaction just stored is
// visible to it (provider_service.py _secret_id_for, _require_usable_secret,
// _register_reference).
type Session struct{ f *Factory }

// NewSession reads and references through f's backend.
func NewSession(f *Factory) Session { return Session{f: f} }

// Manager is the session's workspace's backend.
func (s Session) Manager(sess db.Session, userID string) kernel.Manager {
	return s.f.Manager(sess, userID)
}

// Secret is the row with id in the session's workspace.
func (Session) Secret(ctx context.Context, sess db.Session, id string) (kernel.Secret, bool, error) {
	sec, err := getByID(ctx, sess.Q(), sess.Workspace().ID(), id)
	if errors.Is(err, kernel.ErrNotFound) {
		return kernel.Secret{}, false, nil
	}
	if err != nil {
		return kernel.Secret{}, false, err
	}
	return sec, true, nil
}

// SecretNamed is the row named name in the session's workspace.
func (Session) SecretNamed(ctx context.Context, sess db.Session, name string) (kernel.Secret, bool, error) {
	return getByName(ctx, sess.Q(), sess.Workspace().ID(), name)
}

// StageReferences replaces a consumer's references in the session's transaction.
func (Session) StageReferences(ctx context.Context, sess db.Session, consumerType, consumerID string, refs []kernel.Reference) error {
	c := &Catalog{ws: sess.Workspace()}
	return c.StageReferences(ctx, sess, consumerType, consumerID, refs)
}
