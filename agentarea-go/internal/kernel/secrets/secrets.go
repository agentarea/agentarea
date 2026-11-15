// Package secrets stores and resolves secret values (AGENTAREA_SECRET_*):
// the database store (encrypted_secrets, Fernet with
// AGENTAREA_SECRET_ENCRYPTION_KEY) or Infisical, selected by
// AGENTAREA_SECRET_BACKEND. Three readers exist today (Python, mcp-manager,
// event-service); this package replaces all of them.
//
// Secrets are kept by reference: callers store a Ref and resolve it at the
// moment of use, never copy the value into another row or payload.
package secrets

import (
	"context"
	"errors"
)

// ErrNotFound is a secret that does not exist.
var ErrNotFound = errors.New("secret not found")

// ErrExternalValue is a catalog row whose value lives in another store than
// the one asked (infrastructure database_secret_manager.py: the database
// backend cannot read a row that points at Infisical, and "not found" would
// send the caller looking for a missing secret).
var ErrExternalValue = errors.New("secret is backed by an external provider; this backend cannot resolve it")

// ErrDecrypt is a stored ciphertext the configured key cannot open. The text
// is Python's; the cause is never wrapped, because it can carry key material.
var ErrDecrypt = errors.New("Failed to decrypt secret. Key may have changed.") //nolint:staticcheck // Python's message, kept for operators

// Ref names a secret by its stored name; resolving it yields the value.
type Ref string

// Manager is the backend (infrastructure/secret_manager.py BaseSecretManager),
// bound to one workspace: two workspaces may use the same name.
type Manager interface {
	// Get returns the value, or ErrNotFound.
	Get(ctx context.Context, name string) (string, error)
	Set(ctx context.Context, name, value string) error
	// Delete reports whether something was deleted.
	Delete(ctx context.Context, name string) (bool, error)
	// Has answers from the row, never from the plaintext: a ciphertext the
	// key can no longer open still "exists".
	Has(ctx context.Context, name string) (bool, error)
	// ExternalRef is the backend's own reference for name, when it has one
	// (Infisical); the database backend keeps the value in the catalog row
	// itself and has none.
	ExternalRef(name string) (string, bool)
}

// Cipher is Fernet, byte-compatible with the cryptography package, so rows of
// encrypted_secrets written by either backend decrypt in the other.
type Cipher interface {
	Encrypt(plaintext []byte) (token string, err error)
	Decrypt(token string) ([]byte, error)
}

// Resolver turns a reference into its value at the moment of use.
type Resolver interface {
	Resolve(ctx context.Context, ref Ref) (string, error)
}
