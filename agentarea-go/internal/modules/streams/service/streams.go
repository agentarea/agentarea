package service

import (
	"context"
	"fmt"
	"slices"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
)

// StreamListLimit is the most streams a stream-name lookup reads (list_streams(limit=1000)).
const StreamListLimit = 1000

func parseStreamID(id string) (uuid.UUID, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return uuid.UUID{}, domain.StreamNotFound(id)
	}
	return u, nil
}

// readable is readable_resource_ids: the resource ids the caller's subject may read.
func (s *Service) readable(ctx context.Context, c authn.Caller) ([]string, error) {
	ids, err := authz.ReadableResourceIDs(ctx, s.d.Graph, c.GraphSubject())
	if err != nil {
		return nil, err
	}
	out := make([]string, 0, len(ids))
	for id := range ids {
		out = append(out, id)
	}
	slices.Sort(out)
	return out, nil
}

// RequireStream is the route's requires(permission, "stream", stream_id).
func (s *Service) RequireStream(ctx context.Context, permission, streamID string) error {
	c, err := callerOf(ctx)
	if err != nil {
		return err
	}
	return s.perms.Require(ctx, c, permission, "stream", streamID)
}

// ListStreams is list_streams narrowed to the streams the caller may read.
func (s *Service) ListStreams(ctx context.Context, limit, offset int) ([]domain.Stream, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return nil, err
	}
	ids, err := s.readable(ctx, c)
	if err != nil {
		return nil, err
	}
	var out []domain.Stream
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		out, err = s.ss.ListStreams(ctx, sess, ids, int32(limit), int32(offset)) //nolint:gosec // bounded by the route
		return err
	})
	return out, err
}

// CreateStream is create_stream: the platform stream's name is refused; the creator owns the stream.
func (s *Service) CreateStream(ctx context.Context, name, description string) (domain.Stream, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return domain.Stream{}, err
	}
	if name == domain.PlatformStreamName {
		return domain.Stream{}, domain.Fail(domain.ErrNameTaken,
			fmt.Sprintf("%s is the name of the workspace's platform stream", domain.PyRepr(name)))
	}
	var out domain.Stream
	err = s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		out, err = s.ss.InsertStream(ctx, sess, domain.Stream{
			ID: uuid.NewString(), Name: name, Description: description, Kind: domain.StreamCustom, CreatedBy: c.UserID,
		}, s.now())
		return err
	})
	if err != nil {
		return domain.Stream{}, err
	}
	if err := authz.GrantResourceOwner(ctx, s.d.Graph, out.ID, c.Workspace.ID(), authz.UserSubject(c.UserID), authz.OwnerRelations()); err != nil {
		return domain.Stream{}, err
	}
	return out, nil
}

// GetStream is get_stream.
func (s *Service) GetStream(ctx context.Context, id string) (domain.Stream, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return domain.Stream{}, err
	}
	var out domain.Stream
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		out, err = s.getStream(ctx, sess, id)
		return err
	})
	return out, err
}

func (s *Service) getStream(ctx context.Context, sess db.Session, id string) (domain.Stream, error) {
	u, err := parseStreamID(id)
	if err != nil {
		return domain.Stream{}, err
	}
	st, ok, err := s.ss.GetStream(ctx, sess, u)
	if err != nil {
		return domain.Stream{}, err
	}
	if !ok {
		return domain.Stream{}, domain.StreamNotFound(id)
	}
	return st, nil
}

// ensureDeletable is ensure_deletable: the stream row stays locked until commit.
func (s *Service) ensureDeletable(ctx context.Context, sess db.Session, id uuid.UUID) error {
	st, ok, err := s.ss.LockForDelete(ctx, sess, id)
	if err != nil {
		return err
	}
	if !ok {
		return domain.StreamNotFound(id.String())
	}
	if st.Kind == domain.StreamPlatform {
		return domain.Fail(domain.ErrManagedByPlatform,
			fmt.Sprintf("Stream %s is the workspace's platform stream and cannot be deleted", id))
	}
	triggers, err := s.ss.TriggerIDsOnStream(ctx, sess, id)
	if err != nil {
		return err
	}
	writers, err := s.ss.WritersInto(ctx, sess, id)
	if err != nil {
		return err
	}
	if len(triggers) == 0 && len(writers) == 0 {
		return nil
	}
	var forwards, processors [][2]string
	for _, w := range writers {
		switch w.Kind {
		case domain.SubForward:
			forwards = append(forwards, [2]string{w.ID, w.StreamID})
		case domain.SubProcessor:
			processors = append(processors, [2]string{w.ID, w.StreamID})
		}
	}
	return domain.InUse(id.String(), triggers, forwards, processors)
}

// DeleteStream is delete_stream_with_sources: refused while a trigger subscribes to it or a
// forward or processor writes into it; its sources' credentials and its external subscribers'
// secrets go with it.
func (s *Service) DeleteStream(ctx context.Context, id string) error {
	c, err := callerOf(ctx)
	if err != nil {
		return err
	}
	u, err := parseStreamID(id)
	if err != nil {
		return err
	}
	return s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		if err := s.ensureDeletable(ctx, sess, u); err != nil {
			return err
		}
		sources, err := s.ss.ListSources(ctx, sess, u)
		if err != nil {
			return err
		}
		for _, src := range sources {
			if err := s.releaseSource(ctx, sess, c, src); err != nil {
				return err
			}
		}
		external, err := s.ss.ExternalOnStream(ctx, sess, u)
		if err != nil {
			return err
		}
		if err := s.releaseSubscriberSecrets(ctx, sess, c, external); err != nil {
			return err
		}
		ok, err := s.ss.DeleteStream(ctx, sess, u)
		if err != nil {
			return err
		}
		if !ok {
			return domain.StreamNotFound(id)
		}
		return subscriptionsChanged(ctx, sess, c.UserID, u.String())
	})
}
