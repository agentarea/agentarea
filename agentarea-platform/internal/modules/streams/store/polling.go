package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
)

// PolledSource is one stream_sources row the pollers act on, in any workspace.
type PolledSource struct {
	ID             string
	WorkspaceID    string
	CreatedBy      string
	Kind           string
	Slug           string
	WebhookID      string
	CredentialKey  string
	Config         map[string]any
	Cursor         string
	RegisteredURL  string
	SubscriptionID string
	RefreshBefore  *time.Time
	PollError      string
	PolledAt       *time.Time
}

// Polling reads the sources of every workspace and records what polling and
// registration did; it runs on db.Global, as one poller serves all workspaces.
type Polling struct{}

// Sources is every poll source and every webhook source with a type, oldest first; a row whose
// config is not JSON is left out and named in the second result.
func (Polling) Sources(ctx context.Context, q db.Querier) ([]PolledSource, []error, error) {
	rows, err := New(q).PollingSources(ctx)
	if err != nil {
		return nil, nil, fmt.Errorf("load stream sources: %w", err)
	}
	out := make([]PolledSource, 0, len(rows))
	var bad []error
	for _, r := range rows {
		src := PolledSource{
			ID: r.ID.String(), WorkspaceID: r.WorkspaceID, CreatedBy: r.CreatedBy, Kind: r.Kind,
			Slug: r.WebhookType.String, WebhookID: r.WebhookID.String, Cursor: r.PollCursor.String,
			RegisteredURL: r.RegisteredUrl.String, SubscriptionID: r.SubscriptionID.String,
			RefreshBefore: fromTZ(r.RefreshBefore), PollError: r.PollError.String, PolledAt: fromTZ(r.PolledAt),
		}
		if r.CredentialKey.Valid {
			src.CredentialKey = r.CredentialKey.UUID.String()
		}
		if len(r.WebhookConfig) > 0 {
			if err := json.Unmarshal(r.WebhookConfig, &src.Config); err != nil {
				bad = append(bad, fmt.Errorf("stream source %s config is not JSON: %w", src.ID, err))
				continue
			}
		}
		out = append(out, src)
	}
	return out, bad, nil
}

func sourceID(id string) (uuid.UUID, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return uuid.UUID{}, fmt.Errorf("stream source id %q: %w", id, err)
	}
	return u, nil
}

// Polled records a successful poll; cursor "" keeps the stored one.
func (Polling) Polled(ctx context.Context, q db.Querier, id, cursor string, now time.Time) error {
	u, err := sourceID(id)
	if err != nil {
		return err
	}
	return New(q).SourcePolled(ctx, SourcePolledParams{Cursor: cursor, Now: tz(now), ID: u})
}

// Failed records why the last poll or registration of a source failed.
func (Polling) Failed(ctx context.Context, q db.Querier, id, reason string, now time.Time) error {
	u, err := sourceID(id)
	if err != nil {
		return err
	}
	return New(q).SourceFailed(ctx, SourceFailedParams{Now: tz(now), Reason: text(&reason), ID: u})
}

// SubscribeFailed records why subscribing an mcp_events source failed; the next attempt is at
// retryAt, so refresh_before - polled_at is the wait it was given.
func (Polling) SubscribeFailed(ctx context.Context, q db.Querier, id, reason string, now, retryAt time.Time) error {
	u, err := sourceID(id)
	if err != nil {
		return err
	}
	return New(q).SourceSubscribeFailed(ctx, SourceSubscribeFailedParams{Reason: text(&reason), Now: tz(now), RetryAt: tz(retryAt), ID: u})
}

// Subscribed records an mcp_events grant: the URL, its id, when to refresh (nil: never) and the
// watermark cursor ("" keeps the stored one).
func (Polling) Subscribed(ctx context.Context, q db.Querier, id, url, subscriptionID string, refreshBefore *time.Time, cursor string) error {
	u, err := sourceID(id)
	if err != nil {
		return err
	}
	return New(q).SourceSubscribed(ctx, SourceSubscribedParams{
		Url: text(&url), SubscriptionID: text(&subscriptionID), RefreshBefore: nullTZ(refreshBefore), Cursor: cursor, ID: u,
	})
}

// Registered records the webhook URL now registered with the provider; "" records none is.
func (Polling) Registered(ctx context.Context, q db.Querier, id, url string) error {
	u, err := sourceID(id)
	if err != nil {
		return err
	}
	return New(q).SourceRegistered(ctx, SourceRegisteredParams{Url: url, ID: u})
}

// ExternalSubscription is the active, unexpired external subscription of ws, false when none.
func (Streams) ExternalSubscription(ctx context.Context, s db.Session, id string) (domain.Subscription, bool, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return domain.Subscription{}, false, nil
	}
	r, err := New(s.Q()).ActiveExternalSubscription(ctx, ActiveExternalSubscriptionParams{WorkspaceID: s.Workspace().ID(), ID: u})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return domain.Subscription{}, false, nil
		}
		return domain.Subscription{}, false, err
	}
	return ToSubscription(r), true, nil
}

// RecordDelivery stores a delivery attempt's outcome: success clears the error, a failure keeps
// the time of the first one.
func (Streams) RecordDelivery(ctx context.Context, s db.Session, id string, at time.Time, deliveryErr string) error {
	u, err := uuid.Parse(id)
	if err != nil {
		return err
	}
	q := New(s.Q())
	if deliveryErr == "" {
		return q.RecordDeliverySuccess(ctx, RecordDeliverySuccessParams{At: tz(at), WorkspaceID: s.Workspace().ID(), ID: u})
	}
	return q.RecordDeliveryFailure(ctx, RecordDeliveryFailureParams{Error: text(&deliveryErr), At: tz(at), WorkspaceID: s.Workspace().ID(), ID: u})
}

// MarkSubscriptionFailed stops deliveries to the subscriber until it refreshes.
func (Streams) MarkSubscriptionFailed(ctx context.Context, s db.Session, id string) error {
	u, err := uuid.Parse(id)
	if err != nil {
		return err
	}
	return New(s.Q()).MarkSubscriptionFailed(ctx, MarkSubscriptionFailedParams{WorkspaceID: s.Workspace().ID(), ID: u})
}

// DeleteExternalSubscription removes an external subscriber; false when it was gone.
func (Streams) DeleteExternalSubscription(ctx context.Context, s db.Session, id string) (bool, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return false, nil
	}
	n, err := New(s.Q()).DeleteExternalSubscription(ctx, DeleteExternalSubscriptionParams{WorkspaceID: s.Workspace().ID(), ID: u})
	return n > 0, err
}

// ExpiredExternalSubscriptions is every external subscriber past its expiry, in every workspace.
func (Polling) ExpiredExternalSubscriptions(ctx context.Context, q db.Querier) ([]domain.Subscription, error) {
	rows, err := New(q).ExpiredExternalSubscriptions(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]domain.Subscription, 0, len(rows))
	for _, r := range rows {
		out = append(out, ToSubscription(r))
	}
	return out, nil
}
