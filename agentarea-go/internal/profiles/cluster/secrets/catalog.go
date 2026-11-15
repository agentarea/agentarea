package secrets

import (
	"context"
	"errors"
	"fmt"
	"log/slog"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	kernel "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
)

const secretColumns = `id::text, workspace_id, secret_name, description, owner_type, owner_id,
	external_ref, created_by, updated_by, created_at, updated_at`

// Catalog is kernel.Catalog over encrypted_secrets and secret_references,
// bound to one workspace and one actor (catalog_service.py).
type Catalog struct {
	database db.Database
	factory  *Factory
	guard    kernel.Guard
	owners   kernel.Ownership
	audit    kernel.Auditor
	ws       scope.Workspace
	actor    kernel.Actor
}

var _ kernel.Catalog = (*Catalog)(nil)

// NewCatalog binds the catalog to a workspace and actor.
func NewCatalog(database db.Database, f *Factory, guard kernel.Guard, owners kernel.Ownership, audit kernel.Auditor, ws scope.Workspace, actor kernel.Actor) *Catalog {
	return &Catalog{database: database, factory: f, guard: guard, owners: owners, audit: audit, ws: ws, actor: actor}
}

func scanSecret(rows interface{ Scan(...any) error }) (kernel.Secret, error) {
	var s kernel.Secret
	err := rows.Scan(&s.ID, &s.WorkspaceID, &s.Name, &s.Description, &s.OwnerType, &s.OwnerID,
		&s.ExternalRef, &s.CreatedBy, &s.UpdatedBy, &s.CreatedAt, &s.UpdatedAt)
	return s, err
}

func list(ctx context.Context, q db.Querier, sql string, args ...any) ([]kernel.Secret, error) {
	rows, err := q.Query(ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []kernel.Secret
	for rows.Next() {
		s, err := scanSecret(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, rows.Err()
}

func (c *Catalog) read(ctx context.Context, fn func(q db.Querier) error) error {
	s, release, err := c.database.Read(ctx, c.ws)
	if err != nil {
		return err
	}
	defer release()
	return fn(s.Q())
}

func (c *Catalog) ListUser(ctx context.Context) (out []kernel.Secret, err error) {
	err = c.read(ctx, func(q db.Querier) (err error) {
		out, err = list(ctx, q, `SELECT `+secretColumns+` FROM encrypted_secrets
			WHERE workspace_id = $1 AND owner_type IS NULL ORDER BY secret_name`, c.ws.ID())
		return err
	})
	return out, err
}

func (c *Catalog) ListVisible(ctx context.Context) (out []kernel.Secret, err error) {
	err = c.read(ctx, func(q db.Querier) (err error) {
		out, err = list(ctx, q, `SELECT `+secretColumns+` FROM encrypted_secrets
			WHERE workspace_id = $1 AND (owner_type IS NULL OR owner_type = ANY($2))
			ORDER BY (owner_type IS NULL) DESC, secret_name`, c.ws.ID(), kernel.SurfacedOwnerTypes())
		return err
	})
	return out, err
}

func getByID(ctx context.Context, q db.Querier, ws, id string) (kernel.Secret, error) {
	if _, err := uuid.Parse(id); err != nil {
		return kernel.Secret{}, notFoundID(id)
	}
	rows, err := list(ctx, q, `SELECT `+secretColumns+` FROM encrypted_secrets WHERE id = $1::uuid AND workspace_id = $2`, id, ws)
	if err != nil {
		return kernel.Secret{}, err
	}
	if len(rows) == 0 {
		return kernel.Secret{}, notFoundID(id)
	}
	return rows[0], nil
}

func getByName(ctx context.Context, q db.Querier, ws, name string) (kernel.Secret, bool, error) {
	rows, err := list(ctx, q, `SELECT `+secretColumns+` FROM encrypted_secrets WHERE workspace_id = $1 AND secret_name = $2`, ws, name)
	if err != nil || len(rows) == 0 {
		return kernel.Secret{}, false, err
	}
	return rows[0], true, nil
}

func notFoundID(id string) error {
	return &kernel.NotFoundError{Message: fmt.Sprintf("No secret %s in this workspace", id)}
}

func notFoundName(name string) error {
	return &kernel.NotFoundError{Message: fmt.Sprintf("No secret named '%s' in this workspace", name)}
}

func (c *Catalog) Get(ctx context.Context, id string) (out kernel.Secret, err error) {
	err = c.read(ctx, func(q db.Querier) (err error) {
		out, err = getByID(ctx, q, c.ws.ID(), id)
		return err
	})
	return out, err
}

func (c *Catalog) GetByName(ctx context.Context, name string) (out kernel.Secret, err error) {
	err = c.read(ctx, func(q db.Querier) error {
		s, ok, err := getByName(ctx, q, c.ws.ID(), name)
		if err == nil && !ok {
			err = notFoundName(name)
		}
		out = s
		return err
	})
	return out, err
}

// requireUserOwned refuses a row a connection owns: those are changed through the connection.
func requireUserOwned(s kernel.Secret) error {
	if s.OwnerType == nil {
		return nil
	}
	ownerID := ""
	if s.OwnerID != nil {
		ownerID = *s.OwnerID
	}
	return &kernel.ManagedError{Message: fmt.Sprintf("Secret '%s' is managed by %s %s. Change it there instead.", s.Name, *s.OwnerType, ownerID)}
}

// requireUsable is can_use_secret on the secret, held by its creator or a workspace admin.
func (c *Catalog) requireUsable(ctx context.Context, s kernel.Secret) (kernel.Secret, error) {
	ok, err := c.guard.CanUseSecret(ctx, c.actor.GraphSubject, s.ID)
	if err != nil {
		return kernel.Secret{}, err
	}
	if !ok {
		return kernel.Secret{}, &kernel.AccessDeniedError{Message: fmt.Sprintf(
			"You may not use secret '%s': it is used by its creator or a workspace admin.", s.Name)}
	}
	return s, nil
}

// GetForUse: using a secret sends its value somewhere the caller chooses, so
// workspace membership is not enough; the graph decides.
func (c *Catalog) GetForUse(ctx context.Context, id string) (kernel.Secret, error) {
	s, err := c.Get(ctx, id)
	if err != nil {
		return kernel.Secret{}, err
	}
	if err := requireUserOwned(s); err != nil {
		return kernel.Secret{}, err
	}
	return c.requireUsable(ctx, s)
}

func (c *Catalog) GetNamedForUse(ctx context.Context, name string) (kernel.Secret, error) {
	s, err := c.GetByName(ctx, name)
	if err != nil {
		return kernel.Secret{}, err
	}
	if s.OwnerType != nil {
		return kernel.Secret{}, &kernel.ManagedError{Message: fmt.Sprintf(
			"Secret '%s' is managed by %s and cannot be referenced.", s.Name, *s.OwnerType)}
	}
	return c.requireUsable(ctx, s)
}

func (c *Catalog) Consumers(ctx context.Context, id string) (out []kernel.ConsumerRef, err error) {
	err = c.read(ctx, func(q db.Querier) error {
		out, err = consumers(ctx, q, c.ws.ID(), id)
		return err
	})
	return out, err
}

func consumers(ctx context.Context, q db.Querier, ws, id string) ([]kernel.ConsumerRef, error) {
	rows, err := q.Query(ctx, `SELECT consumer_type, consumer_id, field FROM secret_references
		WHERE secret_id = $1::uuid AND workspace_id = $2`, id, ws)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []kernel.ConsumerRef
	for rows.Next() {
		var r kernel.ConsumerRef
		if err := rows.Scan(&r.ConsumerType, &r.ConsumerID, &r.Field); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

func (c *Catalog) record(ctx context.Context, s db.Session, action string, sec kernel.Secret, changes ...kernel.Change) error {
	return c.audit.Record(ctx, s, kernel.AuditEntry{Action: action, SecretID: sec.ID, ResourceName: sec.Name, Changes: changes})
}

// creator is a backend whose catalog row is the value, so the row's insert
// is the create.
type creator interface {
	Create(ctx context.Context, name, value string, description *string) error
}

// CreateUser stores the value and its catalog row in one transaction. The
// row's insert claims the name, and a concurrent create of the same name
// waits for it and loses with DuplicateNameError: it never overwrites the
// first one's value or becomes its owner. For Infisical the row goes in before
// the value, so the loser never reaches Infisical. A failed owner grant takes
// the value back out: a secret no one may use would only block its own name.
func (c *Catalog) CreateUser(ctx context.Context, name, value string, description *string) (kernel.Secret, error) {
	if err := kernel.ValidateUserName(name); err != nil {
		return kernel.Secret{}, err
	}
	var created kernel.Secret
	err := c.database.Write(ctx, c.ws, func(ctx context.Context, s db.Session) error {
		mgr := c.factory.Manager(s, c.actor.UserID)
		ref, external := mgr.ExternalRef(name)
		if cr, ok := mgr.(creator); ok {
			if err := cr.Create(ctx, name, value, description); err != nil {
				return err
			}
		} else {
			if _, err := s.Q().Exec(ctx, `INSERT INTO encrypted_secrets
				(id, workspace_id, secret_name, encrypted_value, external_ref, description, created_by)
				VALUES ($1::uuid, $2, $3, NULL, $4, $5, $6)`,
				uuid.NewString(), c.ws.ID(), name, ref, description, c.actor.UserID); err != nil {
				if uniqueViolation(err) {
					return &kernel.DuplicateNameError{Name: name}
				}
				return err
			}
			if err := mgr.Set(ctx, name, value); err != nil {
				return err
			}
		}
		sec, ok, err := getByName(ctx, s.Q(), c.ws.ID(), name)
		if err != nil {
			return err
		}
		if !ok {
			return notFoundName(name)
		}
		if err := c.owners.GrantOwner(ctx, sec.ID, c.ws.ID(), c.actor.GraphSubject); err != nil {
			if external {
				if _, derr := mgr.Delete(ctx, name); derr != nil {
					slog.ErrorContext(ctx, "could not take back a secret whose owner grant failed", "workspace_id", c.ws.ID(), "error_type", fmt.Sprintf("%T", derr))
				}
			}
			return err
		}
		if err := c.record(ctx, s, "secret.create", sec); err != nil {
			return err
		}
		created = sec
		return nil
	})
	if err != nil {
		return kernel.Secret{}, err
	}
	slog.InfoContext(ctx, "Created user secret", "workspace_id", c.ws.ID())
	return created, nil
}

// RotateUser writes the new value. That it changed is audited, what it changed to is not.
func (c *Catalog) RotateUser(ctx context.Context, id, value string) (kernel.Secret, error) {
	var out kernel.Secret
	err := c.database.Write(ctx, c.ws, func(ctx context.Context, s db.Session) error {
		sec, err := getByID(ctx, s.Q(), c.ws.ID(), id)
		if err != nil {
			return err
		}
		if err := requireUserOwned(sec); err != nil {
			return err
		}
		if err := c.factory.Manager(s, c.actor.UserID).Set(ctx, sec.Name, value); err != nil {
			return err
		}
		if sec.ExternalRef != nil {
			if _, err := s.Q().Exec(ctx, `UPDATE encrypted_secrets SET updated_by = $2, updated_at = now() WHERE id = $1::uuid`,
				sec.ID, c.actor.UserID); err != nil {
				return err
			}
		}
		if err := c.record(ctx, s, "secret.rotate", sec, kernel.Change{Field: "value", Before: "***", After: "***"}); err != nil {
			return err
		}
		out, err = getByID(ctx, s.Q(), c.ws.ID(), id)
		return err
	})
	if err != nil {
		return kernel.Secret{}, err
	}
	slog.InfoContext(ctx, "Rotated user secret", "workspace_id", c.ws.ID())
	return out, nil
}

func (c *Catalog) UpdateDescription(ctx context.Context, id string, description *string) (kernel.Secret, error) {
	var out kernel.Secret
	err := c.database.Write(ctx, c.ws, func(ctx context.Context, s db.Session) error {
		sec, err := getByID(ctx, s.Q(), c.ws.ID(), id)
		if err != nil {
			return err
		}
		if err := requireUserOwned(sec); err != nil {
			return err
		}
		if _, err := s.Q().Exec(ctx, `UPDATE encrypted_secrets SET description = $2, updated_by = $3, updated_at = now()
			WHERE id = $1::uuid`, sec.ID, description, c.actor.UserID); err != nil {
			return err
		}
		if err := c.record(ctx, s, "secret.update", sec, kernel.Change{Field: "description", Before: sec.Description, After: description}); err != nil {
			return err
		}
		out, err = getByID(ctx, s.Q(), c.ws.ID(), id)
		return err
	})
	return out, err
}

// foreignKeyViolation is a Postgres integrity error from the delete without
// importing the driver: RESTRICT reports 23001, NO ACTION 23503, and Python
// catches the whole class (IntegrityError).
func foreignKeyViolation(err error) bool {
	var state interface{ SQLState() string }
	return errors.As(err, &state) && (state.SQLState() == "23001" || state.SQLState() == "23503")
}

func uniqueViolation(err error) bool {
	var state interface{ SQLState() string }
	return errors.As(err, &state) && state.SQLState() == "23505"
}

// DeleteUser lets the database be the guard: RESTRICT on secret_references
// (or a column's foreign key) refuses the delete, so a reference created
// concurrently cannot slip through between a check and the delete.
func (c *Catalog) DeleteUser(ctx context.Context, id string) error {
	var gone kernel.Secret
	err := c.database.Write(ctx, c.ws, func(ctx context.Context, s db.Session) error {
		sec, err := getByID(ctx, s.Q(), c.ws.ID(), id)
		if err != nil {
			return err
		}
		if err := requireUserOwned(sec); err != nil {
			return err
		}
		if _, err := s.Q().Exec(ctx, `DELETE FROM encrypted_secrets WHERE id = $1::uuid`, sec.ID); err != nil {
			return err
		}
		if err := c.record(ctx, s, "secret.delete", sec); err != nil {
			return err
		}
		gone = sec
		return nil
	})
	if foreignKeyViolation(err) {
		refs, cerr := c.Consumers(ctx, id)
		if cerr != nil {
			return cerr
		}
		return &kernel.InUseError{Consumers: refs}
	}
	if err != nil {
		return err
	}
	if gone.ExternalRef != nil {
		if ext, ok := c.factory.external(c.ws); ok {
			if _, err := ext.Delete(ctx, gone.Name); err != nil {
				return err
			}
		}
	}
	if err := c.owners.Revoke(ctx, gone.ID); err != nil {
		slog.ErrorContext(ctx, "Deleted secret but could not remove its graph tuples", "secret_id", gone.ID, "error_type", fmt.Sprintf("%T", err))
	}
	slog.InfoContext(ctx, "Deleted user secret", "workspace_id", c.ws.ID())
	return nil
}

// AddReference records a consumer that keeps its reference inside a JSON document.
func (c *Catalog) AddReference(ctx context.Context, secretID, consumerType, consumerID, field string) error {
	return c.database.Write(ctx, c.ws, func(ctx context.Context, s db.Session) error {
		if _, err := getByID(ctx, s.Q(), c.ws.ID(), secretID); err != nil {
			return err
		}
		_, err := s.Q().Exec(ctx, `INSERT INTO secret_references (id, workspace_id, secret_id, consumer_type, consumer_id, field)
			VALUES ($1::uuid, $2, $3::uuid, $4, $5, $6)
			ON CONFLICT (secret_id, consumer_type, consumer_id, field) DO NOTHING`,
			uuid.NewString(), c.ws.ID(), secretID, consumerType, consumerID, field)
		return err
	})
}

// ClearReferences drops every reference a consumer holds, before rewriting them.
func (c *Catalog) ClearReferences(ctx context.Context, consumerType, consumerID string) error {
	return c.database.Write(ctx, c.ws, func(ctx context.Context, s db.Session) error {
		return c.StageReferences(ctx, s, consumerType, consumerID, nil)
	})
}

// StageReferences replaces a consumer's references in the caller's
// transaction. Written with the consumer's own row, a reference cannot be
// missing while the consumer uses the secret, and the foreign key refuses the
// secret's delete for as long as it is.
func (c *Catalog) StageReferences(ctx context.Context, s db.Session, consumerType, consumerID string, refs []kernel.Reference) error {
	if s.Workspace().ID() != c.ws.ID() {
		return errors.New("secret references staged in another workspace's session")
	}
	if _, err := s.Q().Exec(ctx, `DELETE FROM secret_references
		WHERE workspace_id = $1 AND consumer_type = $2 AND consumer_id = $3`, c.ws.ID(), consumerType, consumerID); err != nil {
		return err
	}
	for _, r := range refs {
		if _, err := s.Q().Exec(ctx, `INSERT INTO secret_references (id, workspace_id, secret_id, consumer_type, consumer_id, field)
			VALUES ($1::uuid, $2, $3::uuid, $4, $5, $6)`,
			uuid.NewString(), c.ws.ID(), r.SecretID, consumerType, consumerID, r.Field); err != nil {
			return err
		}
	}
	return nil
}

func (c *Catalog) CountUser(ctx context.Context) (n int, err error) {
	err = c.read(ctx, func(q db.Querier) error {
		_, err := one(ctx, q, `SELECT count(id) FROM encrypted_secrets WHERE workspace_id = $1 AND owner_type IS NULL`,
			[]any{c.ws.ID()}, &n)
		return err
	})
	return n, err
}
