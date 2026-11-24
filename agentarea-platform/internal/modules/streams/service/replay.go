package service

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
)

// ReplayedEvent is the copy ReplayEvent appended.
type ReplayedEvent struct {
	EventID  string `json:"event_id"`
	StreamID string `json:"stream_id"`
	Of       string `json:"replay_of"`
}

// ReplayEvent appends a copy of a stored event to its stream under a new key, so every
// subscription reacts to it as to a new arrival: the same source, sender, session, body and
// files, received now. The copy is caused by the original. The caller must be able to edit the stream.
func (s *Service) ReplayEvent(ctx context.Context, eventID string) (ReplayedEvent, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return ReplayedEvent{}, err
	}
	notFound := domain.Fail(domain.ErrEventNotFound, fmt.Sprintf("Event %s not found", eventID))
	u, err := uuid.Parse(eventID)
	if err != nil {
		return ReplayedEvent{}, notFound
	}
	var ev domain.RecordedEvent
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		var ok bool
		ev, ok, err = s.ss.EventByID(ctx, sess, u)
		if err == nil && !ok {
			return notFound
		}
		return err
	})
	if err != nil {
		return ReplayedEvent{}, err
	}
	if err := s.perms.Require(ctx, c, "edit", "stream", ev.StreamID); err != nil {
		return ReplayedEvent{}, err
	}
	cp := ev.Event
	original := cp.ID
	cp.ID, cp.EventKey, cp.ReceivedAt = "", "replay:"+original+":"+uuid.NewString(), s.now()
	cp.CausationID = &original
	if cp.CorrelationID == nil {
		cp.CorrelationID = &original
	}
	cp.ID = domain.EventIDFor(cp.StreamID, cp.EventKey)
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		_, err := s.Append(ctx, sess, cp)
		return err
	})
	if err != nil {
		return ReplayedEvent{}, err
	}
	s.log.InfoContext(ctx, "Stream event replayed", "event_id", cp.ID, "replay_of", original, "stream_id", cp.StreamID, "user_id", c.UserID)
	return ReplayedEvent{EventID: cp.ID, StreamID: cp.StreamID, Of: original}, nil
}
