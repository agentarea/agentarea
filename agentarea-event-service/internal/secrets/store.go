package secrets

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/agentarea/event-service/internal/template"
)

// ErrNotFound means the workspace has no secret of that name.
var ErrNotFound = errors.New("secret not found")

// Reader reads one secret of a workspace by name.
type Reader interface {
	Get(ctx context.Context, workspaceID, name string) (string, error)
}

// Store reads encrypted_secrets rows and decrypts them.
type Store struct {
	db     *sql.DB
	fernet *Fernet
}

// NewStore wraps the database and the backend's key.
func NewStore(db *sql.DB, fernet *Fernet) *Store {
	return &Store{db: db, fernet: fernet}
}

// Get returns the plaintext of a workspace secret.
func (s *Store) Get(ctx context.Context, workspaceID, name string) (string, error) {
	var encrypted sql.NullString
	err := s.db.QueryRowContext(ctx,
		`SELECT encrypted_value FROM encrypted_secrets WHERE workspace_id = $1 AND secret_name = $2`,
		workspaceID, name,
	).Scan(&encrypted)
	if errors.Is(err, sql.ErrNoRows) {
		return "", fmt.Errorf("%s: %w", name, ErrNotFound)
	}
	if err != nil {
		return "", fmt.Errorf("read secret %s: %w", name, err)
	}
	if !encrypted.Valid {
		return "", fmt.Errorf("secret %s lives in an external store the event service cannot read", name)
	}
	plaintext, err := s.fernet.Decrypt(encrypted.String)
	if err != nil {
		return "", fmt.Errorf("decrypt secret %s: %w", name, err)
	}
	return string(plaintext), nil
}

// CredentialName is where a source's credentials live: one JSON object per
// source, keyed by the catalog slug and the source's credential key.
func CredentialName(slug, credentialKey string) string {
	return "channel_cred:" + slug + ":" + credentialKey
}

// Credentials reads a source's credentials. Each field is a value, or
// {"secret_name": "..."} naming a workspace secret that holds it. A source with
// no credential key, or none stored, has no credentials.
func Credentials(ctx context.Context, r Reader, workspaceID, slug, credentialKey string) (map[string]string, error) {
	if credentialKey == "" {
		return map[string]string{}, nil
	}
	blob, err := r.Get(ctx, workspaceID, CredentialName(slug, credentialKey))
	if errors.Is(err, ErrNotFound) {
		return map[string]string{}, nil
	}
	if err != nil {
		return nil, err
	}
	var fields map[string]any
	if err := json.Unmarshal([]byte(blob), &fields); err != nil {
		return nil, fmt.Errorf("credentials of %s are not a JSON object", slug)
	}
	out := make(map[string]string, len(fields))
	for key, value := range fields {
		ref, isRef := value.(map[string]any)
		if !isRef {
			out[key] = template.Text(value)
			continue
		}
		name, _ := ref["secret_name"].(string)
		if name == "" {
			return nil, fmt.Errorf("credential %s of %s names no secret", key, slug)
		}
		resolved, err := r.Get(ctx, workspaceID, name)
		if err != nil {
			return nil, fmt.Errorf("credential %s of %s: %w", key, slug, err)
		}
		out[key] = resolved
	}
	return out, nil
}
