package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"slices"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
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
// files, received now. The copy is caused by the original. The copy runs as its sender, so
// beside edit on the stream the caller must be that sender (the member who linked the
// messenger account it came from) or administer the workspace.
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
	if ok, err := s.mayReplay(ctx, c, ev.Event); err != nil {
		return ReplayedEvent{}, err
	} else if !ok {
		return ReplayedEvent{}, domain.Refused("Only the person who sent this event, or an admin of the workspace, may replay it: " +
			"the replay runs as its sender")
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

// mayReplay is whether c may replay e: c administers the workspace (owns it), or c is the member
// who linked the messenger account e came from.
func (s *Service) mayReplay(ctx context.Context, c authn.Caller, e domain.Event) (bool, error) {
	if slices.Contains(c.AdminWorkspaces, c.Workspace.ID()) {
		return true, nil
	}
	if s.d.Owners != nil {
		owner, ok, err := s.d.Owners.Owner(ctx, c.Workspace.ID())
		if err != nil {
			return false, err
		}
		if ok && owner == c.UserID {
			return true, nil
		}
	}
	if e.Sender == nil || s.d.Links == nil {
		return false, nil
	}
	door, err := s.EventAdmission(ctx, c.Workspace, e)
	if errors.Is(err, ErrAdmissionLookup) || (err == nil && (door == nil || door.Admission.Identity != Telegram)) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	body, err := s.EventBody(ctx, e)
	if err != nil {
		return false, err
	}
	// The read model hands numbers back as floats; the sender's id is read as the bus carries it.
	raw, err := json.Marshal(map[string]any{"headers": e.Data["headers"], "body": body})
	if err != nil {
		return false, err
	}
	data, err := DecodeJSON(raw)
	if err != nil {
		return false, err
	}
	asMap, _ := data.(map[string]any)
	sender, ok := senderOf(door.Admission, asMap)
	if !ok {
		return false, nil
	}
	holder, linked, err := s.d.Links.Holder(ctx, Telegram, sender.externalID)
	return linked && holder == c.UserID, err
}
