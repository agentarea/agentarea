package service

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/store"
)

// LookupStore is the read side of the lookups (store.Lookup).
type LookupStore interface {
	MCPInstanceExists(ctx context.Context, s db.Session, id uuid.UUID) (bool, error)
	MCPInstanceNames(ctx context.Context, s db.Session, ids []uuid.UUID) (map[uuid.UUID]string, error)
	MCPInstanceFlags(ctx context.Context, s db.Session, ids []uuid.UUID) (store.Managed, error)
	OpenAPIConnectionFlags(ctx context.Context, s db.Session, ids []uuid.UUID) (store.Managed, error)
	OpenAPIConnectionNames(ctx context.Context, s db.Session, ids []uuid.UUID) (map[uuid.UUID]string, error)
}

// Lookup implements api.Lookup over the read pool. An id that is not a UUID
// names nothing.
type Lookup struct {
	DB    db.Database
	Store LookupStore
}

var (
	_ api.Lookup     = (*Lookup)(nil)
	_ api.Attachable = (*Lookup)(nil)
)

// parse keeps the ids that are UUIDs.
func parse(ids []string) []uuid.UUID {
	out := make([]uuid.UUID, 0, len(ids))
	for _, id := range ids {
		if u, err := uuid.Parse(id); err == nil {
			out = append(out, u)
		}
	}
	return out
}

func (l *Lookup) session(ctx context.Context, ws scope.Workspace, fn func(db.Session) error) error {
	s, release, err := l.DB.Read(ctx, ws)
	if err != nil {
		return err
	}
	defer release()
	return fn(s)
}

// MCPInstanceExists is true when ws sees the instance.
func (l *Lookup) MCPInstanceExists(ctx context.Context, ws scope.Workspace, id string) (bool, error) {
	parsed, err := uuid.Parse(id)
	if err != nil {
		return false, nil
	}
	var ok bool
	err = l.session(ctx, ws, func(s db.Session) (err error) {
		ok, err = l.Store.MCPInstanceExists(ctx, s, parsed)
		return err
	})
	return ok, err
}

// MCPInstanceNames maps each id of ids visible to ws to its name.
func (l *Lookup) MCPInstanceNames(ctx context.Context, ws scope.Workspace, ids []string) (map[string]string, error) {
	out := map[string]string{}
	parsed := parse(ids)
	if len(parsed) == 0 {
		return out, nil
	}
	err := l.session(ctx, ws, func(s db.Session) error {
		found, err := l.Store.MCPInstanceNames(ctx, s, parsed)
		for id, name := range found {
			out[id.String()] = name
		}
		return err
	})
	return out, err
}

// MCPInstance reports whether ws sees the instance and whether the platform manages it.
func (l *Lookup) MCPInstance(ctx context.Context, ws scope.Workspace, id string) (bool, bool, error) {
	return l.flags(ctx, ws, id, l.Store.MCPInstanceFlags)
}

// OpenAPIConnection is MCPInstance for an OpenAPI connection.
func (l *Lookup) OpenAPIConnection(ctx context.Context, ws scope.Workspace, id string) (bool, bool, error) {
	return l.flags(ctx, ws, id, l.Store.OpenAPIConnectionFlags)
}

func (l *Lookup) flags(ctx context.Context, ws scope.Workspace, id string,
	read func(context.Context, db.Session, []uuid.UUID) (store.Managed, error)) (bool, bool, error) {
	parsed := parse([]string{id})
	if len(parsed) == 0 {
		return false, false, nil
	}
	var m store.Managed
	err := l.session(ctx, ws, func(s db.Session) (err error) {
		m, err = read(ctx, s, parsed)
		return err
	})
	if err != nil {
		return false, false, err
	}
	managed, found := m[parsed[0]]
	if !found {
		return false, false, nil
	}
	return true, managed != nil && *managed == domain.ManagedByPlatform, nil
}

// OpenAPIConnectionNames maps each id of ids ws sees to its name.
func (l *Lookup) OpenAPIConnectionNames(ctx context.Context, ws scope.Workspace, ids []string) (map[string]string, error) {
	out := map[string]string{}
	parsed := parse(ids)
	if len(parsed) == 0 {
		return out, nil
	}
	err := l.session(ctx, ws, func(s db.Session) error {
		found, err := l.Store.OpenAPIConnectionNames(ctx, s, parsed)
		for id, name := range found {
			out[id.String()] = name
		}
		return err
	})
	return out, err
}
