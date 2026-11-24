// Package secrets implements the kernel secrets ports for a cluster
// deployment: the Postgres-backed store (Fernet over encrypted_secrets), the
// Infisical backend, the catalog over the same table, and the owner-name
// lookup the secrets list shows.
package secrets

import (
	"context"
	"errors"
	"fmt"
	"log/slog"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	kernel "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
)

// Database is the database backend (database_secret_manager.py): rows of
// encrypted_secrets scoped by workspace, values Fernet-encrypted. It runs on
// the session it is given; Set and Delete need a write session, whose
// transaction commits them.
type Database struct {
	s      db.Session
	cipher kernel.Cipher
	userID string
}

var errWriteSession = errors.New("secret writes need a write session (db.Database.Write)")

// NewDatabase binds the store to a workspace session. userID is recorded as
// created_by / updated_by.
func NewDatabase(s db.Session, c kernel.Cipher, userID string) *Database {
	return &Database{s: s, cipher: c, userID: userID}
}

// one runs a query expected to return at most one row and scans it.
func one(ctx context.Context, q db.Querier, sql string, args []any, dest ...any) (bool, error) {
	rows, err := q.Query(ctx, sql, args...)
	if err != nil {
		return false, err
	}
	defer rows.Close()
	if !rows.Next() {
		return false, rows.Err()
	}
	if err := rows.Scan(dest...); err != nil {
		return false, err
	}
	rows.Close()
	return true, rows.Err()
}

// Get decrypts the value. A row that points at an external store is
// ErrExternalValue, not ErrNotFound: the latter would send the caller looking
// for a missing secret instead of a misconfigured backend.
func (d *Database) Get(ctx context.Context, name string) (string, error) {
	return d.get(ctx, name, false)
}

// GetUserOwned is Get limited to the rows a user created.
func (d *Database) GetUserOwned(ctx context.Context, name string) (string, error) {
	return d.get(ctx, name, true)
}

func (d *Database) get(ctx context.Context, name string, userOwned bool) (string, error) {
	sql := `SELECT encrypted_value FROM encrypted_secrets WHERE workspace_id = $1 AND secret_name = $2`
	if userOwned {
		sql += ` AND owner_type IS NULL`
	}
	var token *string
	found, err := one(ctx, d.s.Q(), sql, []any{d.s.Workspace().ID(), name}, &token)
	if err != nil {
		return "", d.fail("retrieve", err)
	}
	if !found {
		return "", kernel.ErrNotFound
	}
	if token == nil {
		return "", fmt.Errorf("secret %q: %w", name, kernel.ErrExternalValue)
	}
	plain, err := d.cipher.Decrypt(*token)
	if err != nil {
		slog.ErrorContext(ctx, "Failed to decrypt secret value", "workspace_id", d.s.Workspace().ID())
		return "", kernel.ErrDecrypt
	}
	return string(plain), nil
}

// Has answers from the row.
func (d *Database) Has(ctx context.Context, name string) (bool, error) {
	var id string
	found, err := one(ctx, d.s.Q(),
		`SELECT id::text FROM encrypted_secrets WHERE workspace_id = $1 AND secret_name = $2`,
		[]any{d.s.Workspace().ID(), name}, &id)
	if err != nil {
		return false, d.fail("check for", err)
	}
	return found, nil
}

// Set creates or updates, for a rotation and the platform's own producers;
// a user's create goes through Create, which never overwrites. An existing
// row keeps its ownership (a rotation must not revert a re-classification); a
// new row is classified by parsing the name the way the catalog does.
func (d *Database) Set(ctx context.Context, name, value string) error {
	if !d.s.InTx() {
		return errWriteSession
	}
	token, err := d.cipher.Encrypt([]byte(value))
	if err != nil {
		return d.fail("encrypt", err)
	}
	var ownerType, ownerID *string
	if o, ok := kernel.ParseManagedName(name); ok {
		ownerType, ownerID = &o.Type, &o.ID
	}
	_, err = d.s.Q().Exec(ctx, `
		INSERT INTO encrypted_secrets
			(id, workspace_id, secret_name, encrypted_value, owner_type, owner_id, created_by)
		VALUES ($1::uuid, $2, $3, $4, $5, $6, $7)
		ON CONFLICT (workspace_id, secret_name) DO UPDATE SET
			encrypted_value = EXCLUDED.encrypted_value,
			external_ref = NULL,
			updated_by = EXCLUDED.created_by,
			updated_at = now()`,
		uuid.NewString(), d.s.Workspace().ID(), name, token, ownerType, ownerID, d.userID)
	if err != nil {
		return d.fail("set", err)
	}
	return nil
}

// Create inserts a user's secret. A name already taken, or held by a create
// not yet committed, is a DuplicateNameError once that one commits: the
// second writer never replaces the first's value or ownership.
func (d *Database) Create(ctx context.Context, name, value string, description *string) error {
	if !d.s.InTx() {
		return errWriteSession
	}
	token, err := d.cipher.Encrypt([]byte(value))
	if err != nil {
		return d.fail("encrypt", err)
	}
	tag, err := d.s.Q().Exec(ctx, `
		INSERT INTO encrypted_secrets (id, workspace_id, secret_name, encrypted_value, description, created_by)
		VALUES ($1::uuid, $2, $3, $4, $5, $6)
		ON CONFLICT (workspace_id, secret_name) DO NOTHING`,
		uuid.NewString(), d.s.Workspace().ID(), name, token, description, d.userID)
	if err != nil {
		return d.fail("create", err)
	}
	if tag.RowsAffected() == 0 {
		return &kernel.DuplicateNameError{Name: name}
	}
	return nil
}

// Delete reports whether a row was removed.
func (d *Database) Delete(ctx context.Context, name string) (bool, error) {
	if !d.s.InTx() {
		return false, errWriteSession
	}
	tag, err := d.s.Q().Exec(ctx,
		`DELETE FROM encrypted_secrets WHERE workspace_id = $1 AND secret_name = $2`,
		d.s.Workspace().ID(), name)
	if err != nil {
		return false, d.fail("delete", err)
	}
	return tag.RowsAffected() > 0, nil
}

// ExternalRef: the row is the value, so there is none.
func (d *Database) ExternalRef(string) (string, bool) { return "", false }

// fail logs the error's type only, as Python does: exception text may carry
// secret material.
func (d *Database) fail(op string, err error) error {
	slog.Error("secret store failed", "op", op, "workspace_id", d.s.Workspace().ID(), "error_type", fmt.Sprintf("%T", err))
	return fmt.Errorf("secret store: failed to %s secret: %w", op, err)
}
