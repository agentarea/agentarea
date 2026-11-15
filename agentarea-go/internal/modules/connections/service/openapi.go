package service

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
)

// ConnectionView is a connection with who may call through it.
type ConnectionView struct {
	Connection domain.Connection
	Sharing    domain.Sharing
}

// actor is the catalog's view of the caller.
func actor(c authn.Caller) ksecrets.Actor {
	return ksecrets.Actor{UserID: c.UserID, GraphSubject: c.GraphSubject()}
}

// ListConnections is one page of the connections the workspace sees.
func (s *Service) ListConnections(ctx context.Context, c authn.Caller, f ConnectionFilter, limit, offset int32) ([]ConnectionView, error) {
	var rows []domain.Connection
	err := s.read(ctx, c, func(sess db.Session) (err error) {
		rows, err = s.d.Connections.List(ctx, sess, f, limit, offset)
		return err
	})
	if err != nil {
		return nil, err
	}
	return s.views(ctx, c, rows)
}

// GetConnection is the connection id the workspace sees.
func (s *Service) GetConnection(ctx context.Context, c authn.Caller, id uuid.UUID) (ConnectionView, error) {
	var conn domain.Connection
	err := s.read(ctx, c, func(sess db.Session) error {
		got, ok, err := s.d.Connections.Get(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return domain.ErrConnectionNotFound()
		}
		conn = got
		return nil
	})
	if err != nil {
		return ConnectionView{}, err
	}
	v, err := s.views(ctx, c, []domain.Connection{conn})
	if err != nil {
		return ConnectionView{}, err
	}
	return v[0], nil
}

// views attaches the sharing of each connection (sharing_of, one graph
// read per row in parallel): personal when the graph marks it so, and
// owned when the caller added it.
func (s *Service) views(ctx context.Context, c authn.Caller, rows []domain.Connection) ([]ConnectionView, error) {
	ids := make([]string, len(rows))
	createdBy := make(map[string]string, len(rows))
	for i, r := range rows {
		ids[i] = r.ID
		createdBy[r.ID] = r.CreatedBy
	}
	sharing, err := s.SharingOf(ctx, c, ids, createdBy)
	if err != nil {
		return nil, err
	}
	out := make([]ConnectionView, 0, len(rows))
	for _, r := range rows {
		out = append(out, ConnectionView{Connection: r, Sharing: sharing[r.ID]})
	}
	return out, nil
}

// DeleteConnection deletes a connection the workspace owns, its header, query
// and URL-variable secrets and the auth configs minted for it. A row the
// workspace does not own (the platform's) is 404 before any secret is touched.
func (s *Service) DeleteConnection(ctx context.Context, c authn.Caller, id uuid.UUID) error {
	var conn domain.Connection
	var owned []domain.AuthConfig
	err := s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		got, ok, err := s.d.Connections.Get(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok || (got.ManagedBy != nil && *got.ManagedBy == domain.ManagedByPlatform) {
			return domain.ErrConnectionNotFound()
		}
		conn = got
		owned, err = s.d.Auth.OwnedByConnection(ctx, sess, id)
		if err != nil {
			return err
		}
		m := s.d.Secrets.Manager(sess, c.UserID)
		for _, name := range conn.SecretNames() {
			if _, err := m.Delete(ctx, name); err != nil {
				return err
			}
		}
		for _, a := range owned {
			if a.SecretKey != nil {
				if _, err := m.Delete(ctx, *a.SecretKey); err != nil {
					return err
				}
			}
		}
		return nil
	})
	if err != nil {
		return err
	}
	for _, a := range owned {
		if err := s.d.Catalog(c.Workspace, actor(c)).ClearReferences(ctx, "mcp_auth_config", a.ID); err != nil {
			return err
		}
	}
	return s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		ok, err := s.d.Connections.Delete(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return domain.ErrConnectionNotFound()
		}
		return nil
	})
}
