package service

import (
	"context"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store"
)

// ExecutionHistory is get_execution_history: the trigger's executions, newest
// first, from offset; none for a trigger the workspace does not have.
func (s *Service) ExecutionHistory(ctx context.Context, triggerID string, limit, offset int) ([]domain.Execution, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return nil, err
	}
	u, err := uuid.Parse(triggerID)
	if err != nil {
		return nil, domain.Invalid("trigger_id must be a UUID")
	}
	var rows []domain.Execution
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		rows, _, err = s.st.ExecutionsPage(ctx, sess, u, store.ExecutionFilter{}, max(limit, 0), max(offset, 0))
		return err
	})
	return rows, err
}

// findStream is find_stream: a stream of the workspace by its id or, failing that, its name.
func (s *Service) findStream(ctx context.Context, sess db.Session, nameOrID string) (domain.Stream, error) {
	if u, err := uuid.Parse(nameOrID); err == nil {
		st, ok, err := s.ss.GetStream(ctx, sess, u)
		if err != nil {
			return domain.Stream{}, err
		}
		if ok {
			return st, nil
		}
	}
	st, ok, err := s.ss.GetStreamByName(ctx, sess, nameOrID)
	if err != nil {
		return domain.Stream{}, err
	}
	if !ok {
		return domain.Stream{}, domain.StreamNotFound(nameOrID)
	}
	return st, nil
}

// pyISO is datetime.isoformat() of an aware time in UTC.
func pyISO(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/1000 != 0 {
		return t.Format("2006-01-02T15:04:05.000000-07:00")
	}
	return t.Format("2006-01-02T15:04:05-07:00")
}

// ReadStreamEvents is stream_events_read_stream: the events of the stream
// named or identified by ref after sequence after, oldest first, the caller
// holding read on it; since keeps those received from then on.
func (s *Service) ReadStreamEvents(ctx context.Context, ref string, after int64, limit int, since *time.Time) (api.StreamEventsRead, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return api.StreamEventsRead{}, err
	}
	var found domain.Stream
	var fetched []domain.RecordedEvent
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		if found, err = s.findStream(ctx, sess, ref); err != nil {
			return err
		}
		if err := s.perms.Require(ctx, c, "read", "stream", found.ID); err != nil {
			return err
		}
		u := uuid.MustParse(found.ID)
		n := int32(limit + 1) //nolint:gosec // bounded by the tool
		if since != nil {
			fetched, err = s.ss.EventsSince(ctx, sess, u, *since, after, n)
		} else {
			fetched, err = s.ss.EventsAfter(ctx, sess, u, after, n)
		}
		return err
	})
	if err != nil {
		return api.StreamEventsRead{}, err
	}
	events := fetched[:min(limit, len(fetched))]
	out := api.StreamEventsRead{
		Stream: api.StreamRef{ID: found.ID, Name: found.Name}, Untrusted: untrustedDataNotice,
		Events: make([]api.StreamEventItem, len(events)), NextAfter: after, HasMore: len(fetched) > limit,
	}
	for i, e := range events {
		data := e.Data
		if data == nil {
			data = map[string]any{}
		}
		out.Events[i] = api.StreamEventItem{
			Sequence: e.Sequence, Kind: e.Kind, Key: e.EventKey, OccurredAt: pyISO(e.OccurredAt),
			ReceivedAt: pyISO(e.ReceivedAt), Data: scrubCarriedEvent(data),
		}
	}
	if len(events) > 0 {
		out.NextAfter = events[len(events)-1].Sequence
	}
	return out, nil
}
