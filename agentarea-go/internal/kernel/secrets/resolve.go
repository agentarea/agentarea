package secrets

import (
	"context"
	"errors"
	"fmt"
)

// ParseReference reads {"secret_name": "..."}, the shape a spec field uses to
// reference a workspace secret. ok is false for a literal. A reference naming
// no secret is an error.
func ParseReference(v any) (ref Ref, ok bool, err error) {
	var name string
	switch r := v.(type) {
	case map[string]any:
		name, _ = r["secret_name"].(string)
	case map[string]string:
		name = r["secret_name"]
	default:
		return "", false, nil
	}
	if name == "" {
		return "", true, errors.New("a secret reference must carry a secret_name")
	}
	return Ref(name), true, nil
}

// UserSecrets reads a workspace's user-owned secrets only: a row the
// platform minted for a connection is part of no workspace's catalog, whatever
// its name.
type UserSecrets interface {
	// GetUserOwned returns the value of the user-owned row, or ErrNotFound.
	GetUserOwned(ctx context.Context, name string) (string, error)
}

// UserResolver resolves references against one workspace's catalog. A
// platform-minted name is refused, and so is any row a connection owns: a
// reference must never read another connection's credential (mcp-manager
// RefuseReservedName and its owner_type IS NULL filter).
type UserResolver struct {
	s UserSecrets
}

// NewUserResolver binds the resolver to a workspace's user secrets.
func NewUserResolver(s UserSecrets) *UserResolver { return &UserResolver{s: s} }

// Resolve reads the value on every call, so a rotated secret reaches the next use.
func (r *UserResolver) Resolve(ctx context.Context, ref Ref) (string, error) {
	if p := ReservedPrefix(string(ref)); p != "" {
		return "", fmt.Errorf("secret %s has the platform-reserved prefix %q", ref, p)
	}
	return r.s.GetUserOwned(ctx, string(ref))
}

// ResolveValues turns an environment or header map into strings: a literal
// passes through fmt.Sprint, a reference is resolved at this moment. An empty
// resolved value is an error, as mcp-manager treats it.
func ResolveValues(ctx context.Context, r Resolver, values map[string]any) (map[string]string, error) {
	out := make(map[string]string, len(values))
	for name, v := range values {
		ref, isRef, err := ParseReference(v)
		if err != nil {
			return nil, fmt.Errorf("%s: %w", name, err)
		}
		if !isRef {
			out[name] = fmt.Sprint(v)
			continue
		}
		if r == nil {
			return nil, fmt.Errorf("%s references secret %s, but no secret resolver is configured", name, ref)
		}
		secret, err := r.Resolve(ctx, ref)
		if err != nil {
			return nil, fmt.Errorf("resolve %s from secret %s: %w", name, ref, err)
		}
		if secret == "" {
			return nil, fmt.Errorf("%s references secret %s, which is empty", name, ref)
		}
		out[name] = secret
	}
	return out, nil
}
