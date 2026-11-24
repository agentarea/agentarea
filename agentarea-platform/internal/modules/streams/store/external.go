package store

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
)

// ExternalByKey is the workspace's external subscriber of that key in any status, false when none.
func (Streams) ExternalByKey(ctx context.Context, s db.Session, externalID string) (domain.Subscription, bool, error) {
	r, err := New(s.Q()).ExternalSubscriptionByKey(ctx, ExternalSubscriptionByKeyParams{
		WorkspaceID: s.Workspace().ID(), ExternalID: text(&externalID)})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Subscription{}, false, nil
	}
	if err != nil {
		return domain.Subscription{}, false, err
	}
	return ToSubscription(r), true, nil
}

// CountExternal is how many external subscribers the workspace has.
func (Streams) CountExternal(ctx context.Context, s db.Session) (int64, error) {
	return New(s.Q()).CountExternalSubscriptions(ctx, s.Workspace().ID())
}

// EndpointVerified is whether this subscriber's callback already answered a challenge here.
func (Streams) EndpointVerified(ctx context.Context, s db.Session, subscriber, callbackURL string) (bool, error) {
	return New(s.Q()).ExternalEndpointVerified(ctx, ExternalEndpointVerifiedParams{
		WorkspaceID: s.Workspace().ID(), Subscriber: text(&subscriber), CallbackUrl: text(&callbackURL)})
}

// InsertExternal writes an active external subscriber: sub's stream, filter, key, subscriber,
// callback, secret name, expiry and verification.
func (Streams) InsertExternal(ctx context.Context, s db.Session, sub domain.Subscription, now time.Time) (domain.Subscription, error) {
	stream, err := uuid.Parse(sub.StreamID)
	if err != nil {
		return domain.Subscription{}, err
	}
	f, err := marshal(sub.Filter)
	if err != nil {
		return domain.Subscription{}, err
	}
	r, err := New(s.Q()).InsertExternalSubscription(ctx, InsertExternalSubscriptionParams{
		ID: uuid.New(), WorkspaceID: s.Workspace().ID(), CreatedBy: sub.CreatedBy, Now: naive(now), StreamID: stream,
		Filter: f, StartedAt: tz(now), ExternalID: text(sub.ExternalID), Subscriber: text(sub.Subscriber),
		CallbackUrl: text(sub.CallbackURL), SecretName: text(sub.SecretName), ExpiresAt: nullTZ(sub.ExpiresAt),
		VerifiedAt: nullTZ(sub.VerifiedAt)})
	if err != nil {
		return domain.Subscription{}, err
	}
	return ToSubscription(r), nil
}

// RefreshExternal gives an external subscriber a new expiry and makes it active again; a
// verification it has is kept.
func (Streams) RefreshExternal(ctx context.Context, s db.Session, id string, expiresAt, verifiedAt, now time.Time) (domain.Subscription, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return domain.Subscription{}, err
	}
	r, err := New(s.Q()).RefreshExternalSubscription(ctx, RefreshExternalSubscriptionParams{
		ExpiresAt: tz(expiresAt), VerifiedAt: tz(verifiedAt), Now: naive(now), WorkspaceID: s.Workspace().ID(), ID: u})
	if err != nil {
		return domain.Subscription{}, err
	}
	return ToSubscription(r), nil
}
