package service

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
)

// Callbacks checks and challenges a subscriber's callback endpoint (WebhookEndpoint); a refusal
// is an *api.EventsError.
type Callbacks interface {
	Check(ctx context.Context, url string) error
	Challenge(ctx context.Context, url, secret, subscription string) error
}

// EventsPage is one events/poll page (PollPage): Position is the sequence of the last row
// scanned, everything up to it answered or not matching.
type EventsPage struct {
	Events   []domain.RecordedEvent
	Position int64
	HasMore  bool
}

const (
	eventsScanLimit = 1000
	eventsChunk     = 200
)

// EventStreams are the streams c may read in its workspace (MCPEvents.list).
func (s *Service) EventStreams(ctx context.Context, c authn.Caller) ([]domain.Stream, error) {
	return s.ListStreams(authn.WithCaller(ctx, c), StreamListLimit, 0)
}

// EventStream is whether c's workspace has the stream, and whether c may read it.
func (s *Service) EventStream(ctx context.Context, c authn.Caller, id string) (found, readable bool, err error) {
	if _, err := s.GetStream(authn.WithCaller(ctx, c), id); err != nil {
		if errors.Is(err, domain.ErrStreamNotFound) {
			return false, false, nil
		}
		return false, false, err
	}
	readable, err = s.perms.Check(ctx, c.GraphSubject(), "read", "stream", id)
	return true, readable, err
}

// EventsHead is the sequence of the stream's newest event in the read model, 0 when it has none.
func (s *Service) EventsHead(ctx context.Context, c authn.Caller, streamID string) (int64, error) {
	id, err := uuid.Parse(streamID)
	if err != nil {
		return 0, err
	}
	var head int64
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		head, err = s.ss.HeadSequence(ctx, sess, id)
		return err
	})
	return head, err
}

// EventsAfter is read_page: up to limit events past after and received since, that f admits.
// A page scans at most eventsScanLimit rows; the position then stands past what was scanned.
func (s *Service) EventsAfter(ctx context.Context, c authn.Caller, streamID string, after int64, since time.Time, f domain.EventFilter, limit int) (EventsPage, error) {
	id, err := uuid.Parse(streamID)
	if err != nil {
		return EventsPage{}, err
	}
	page := EventsPage{Position: after}
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		scanned := 0
		for scanned < eventsScanLimit {
			chunk := min(eventsChunk, eventsScanLimit-scanned)
			rows, err := s.ss.EventsSince(ctx, sess, id, since, page.Position, int32(chunk)) //nolint:gosec // at most eventsChunk
			if err != nil {
				return err
			}
			for i, row := range rows {
				scanned++
				page.Position = row.Sequence
				if !f.Admits(row.Event) {
					continue
				}
				page.Events = append(page.Events, row)
				if len(page.Events) == limit {
					if i < len(rows)-1 {
						page.HasMore = true
						return nil
					}
					more, err := s.ss.EventsSince(ctx, sess, id, since, page.Position, 1)
					page.HasMore = len(more) > 0
					return err
				}
			}
			if len(rows) < chunk {
				return nil
			}
		}
		page.HasMore = true
		return nil
	})
	return page, err
}

// ExternalSubscribe is one events/subscribe at Now: the subscriber key's parts, its secret and
// the TTL suggested (nil: none).
type ExternalSubscribe struct {
	StreamID   string
	Subscriber string
	URL        string
	Secret     string
	Arguments  domain.EventArguments
	TTLMs      *int64
	Now        time.Time
}

// Subscribed is a created or refreshed subscriber and the expiry granted; Existing is what it
// was before a refresh.
type Subscribed struct {
	ID            string
	RefreshBefore time.Time
	Existing      *domain.Subscription
}

// SubscribeExternal is ExternalSubscriptions.subscribe: the secret checked, the callback
// checked, challenged before the first delivery to a (subscriber, URL), then the subscriber
// created, or refreshed with a new expiry and active again.
func (s *Service) SubscribeExternal(ctx context.Context, c authn.Caller, cb Callbacks, in ExternalSubscribe) (Subscribed, error) {
	if err := domain.ValidateWebhookSecret(in.Secret); err != nil {
		return Subscribed{}, err
	}
	if err := cb.Check(ctx, in.URL); err != nil {
		return Subscribed{}, err
	}
	key := domain.SubscriptionKey(in.Subscriber, in.URL, in.StreamID, in.Arguments)
	out := Subscribed{ID: key, RefreshBefore: domain.GrantRefreshBefore(in.TTLMs, in.Now)}
	var verified bool
	err := s.read(ctx, c.Workspace, func(sess db.Session) error {
		existing, ok, err := s.ss.ExternalByKey(ctx, sess, key)
		if err != nil || ok {
			if ok {
				out.Existing = &existing
			}
			return err
		}
		verified, err = s.ss.EndpointVerified(ctx, sess, in.Subscriber, in.URL)
		return err
	})
	if err != nil {
		return Subscribed{}, err
	}
	if out.Existing == nil && !verified {
		if err := cb.Challenge(ctx, in.URL, in.Secret, key); err != nil {
			return Subscribed{}, err
		}
	}
	now := in.Now
	name := SubscriberSecretName(key)
	err = s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		if err := s.d.Secrets.Manager(sess, c.UserID).Set(ctx, name, in.Secret); err != nil {
			return err
		}
		if _, err := s.getStream(ctx, sess, in.StreamID); err != nil {
			return err
		}
		existing, ok, err := s.ss.ExternalByKey(ctx, sess, key)
		if err != nil {
			return err
		}
		if ok {
			_, err = s.ss.RefreshExternal(ctx, sess, existing.ID, out.RefreshBefore, now, now)
		} else {
			err = s.insertExternal(ctx, sess, c, in, key, name, out.RefreshBefore)
		}
		if err != nil {
			return err
		}
		return subscriptionsChanged(ctx, sess, c.UserID, in.StreamID)
	})
	return out, err
}

func (s *Service) insertExternal(ctx context.Context, sess db.Session, c authn.Caller, in ExternalSubscribe, key, name string, expires time.Time) error {
	count, err := s.ss.CountExternal(ctx, sess)
	if err != nil {
		return err
	}
	if count >= domain.MaxExternalSubscriptions {
		return &api.EventsError{Code: api.EventsResourceExhausted,
			Message: fmt.Sprintf("The workspace already has %d external subscriptions", domain.MaxExternalSubscriptions),
			Data:    map[string]any{"limit": "subscriptions", "max": domain.MaxExternalSubscriptions}}
	}
	_, err = s.ss.InsertExternal(ctx, sess, domain.Subscription{
		StreamID: in.StreamID, Filter: in.Arguments.Filter().Dump(), ExternalID: &key, Subscriber: &in.Subscriber,
		CallbackURL: &in.URL, SecretName: &name, ExpiresAt: &expires, VerifiedAt: &in.Now, CreatedBy: c.UserID,
	}, in.Now)
	return err
}

// UnsubscribeExternal is ExternalSubscriptions.unsubscribe: the subscriber of that key removed
// with its secret.
func (s *Service) UnsubscribeExternal(ctx context.Context, c authn.Caller, streamID, subscriber, url string, args domain.EventArguments) error {
	key := domain.SubscriptionKey(subscriber, url, streamID, args)
	return s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		sub, ok, err := s.ss.ExternalByKey(ctx, sess, key)
		if err != nil {
			return err
		}
		if !ok {
			return &api.EventsError{Code: api.EventsNotFound, Message: "no such subscription", Data: map[string]any{"kind": "subscription"}}
		}
		gone, err := s.ss.DeleteExternalSubscription(ctx, sess, sub.ID)
		if err != nil {
			return err
		}
		if !gone {
			return fmt.Errorf("subscription %s: %w", sub.ID, domain.ErrSubscriptionNotFound)
		}
		if err := subscriptionsChanged(ctx, sess, c.UserID, sub.StreamID); err != nil {
			return err
		}
		_, err = s.d.Secrets.Manager(sess, c.UserID).Delete(ctx, SubscriberSecretName(key))
		return err
	})
}

// EventsRetention is how far back the events read model reaches (AGENTAREA_EVENT_RETENTION).
func (s *Service) EventsRetention() time.Duration { return s.d.Settings.Retention }
