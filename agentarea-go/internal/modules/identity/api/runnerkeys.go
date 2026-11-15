package api

import (
	"context"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
)

// RunnerKey is an API key bound to a client's runner (an api_keys row with client_id).
type RunnerKey struct {
	ID         string
	Name       string
	Prefix     string
	CreatedBy  string
	CreatedAt  time.Time
	LastUsedAt *time.Time
	ClientID   *string
	Active     bool
}

// RunnerKeys issues, lists and revokes the keys of clients' runners in the caller's workspace.
type RunnerKeys interface {
	// Issue creates a key named name bound to clientID; the string is the secret, shown once.
	Issue(ctx context.Context, c authn.Caller, clientID, name string) (RunnerKey, string, error)
	// List is every key bound to clientID, revoked ones included, newest first.
	List(ctx context.Context, c authn.Caller, clientID string) ([]RunnerKey, error)
	// Get is one of the workspace's keys of any flavour, false when it has none.
	Get(ctx context.Context, c authn.Caller, keyID string) (RunnerKey, bool, error)
	Revoke(ctx context.Context, c authn.Caller, keyID string) error
}
