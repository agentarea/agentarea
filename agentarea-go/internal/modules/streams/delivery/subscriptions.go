package delivery

import (
	"context"
	"errors"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store"
)

// Subscriptions is what delivery reads and writes of external subscribers.
type Subscriptions interface {
	// Active is the active, unexpired external subscriber id of ws; false when none.
	Active(ctx context.Context, ws scope.Workspace, id string) (domain.Subscription, bool, error)
	// Secret is the subscriber's signing secret as owner reads it; false when it is gone.
	Secret(ctx context.Context, ws scope.Workspace, owner, name string) (string, bool, error)
	Record(ctx context.Context, ws scope.Workspace, id string, at time.Time, deliveryErr string) error
	MarkFailed(ctx context.Context, ws scope.Workspace, id string) error
	// Remove deletes the subscriber, tells the router its stream's subscriptions changed, and
	// deletes its secret, in one transaction.
	Remove(ctx context.Context, ws scope.Workspace, owner string, sub domain.Subscription) error
	// Expired is every external subscriber past its expiry, in every workspace.
	Expired(ctx context.Context) ([]domain.Subscription, error)
}

// Stored is Subscriptions over stream_subscriptions and the workspace's secrets.
type Stored struct {
	DB      db.Database
	Secrets service.Secrets
}

var _ Subscriptions = Stored{}

// Active implements Subscriptions.
func (s Stored) Active(ctx context.Context, ws scope.Workspace, id string) (domain.Subscription, bool, error) {
	sess, release, err := s.DB.Read(ctx, ws)
	if err != nil {
		return domain.Subscription{}, false, err
	}
	defer release()
	return store.Streams{}.ExternalSubscription(ctx, sess, id)
}

// Secret implements Subscriptions.
func (s Stored) Secret(ctx context.Context, ws scope.Workspace, owner, name string) (string, bool, error) {
	if name == "" {
		return "", false, nil
	}
	sess, release, err := s.DB.Read(ctx, ws)
	if err != nil {
		return "", false, err
	}
	defer release()
	v, err := s.Secrets.Manager(sess, owner).Get(ctx, name)
	if errors.Is(err, ksecrets.ErrNotFound) {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	return v, v != "", nil
}

// Record implements Subscriptions.
func (s Stored) Record(ctx context.Context, ws scope.Workspace, id string, at time.Time, deliveryErr string) error {
	return s.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		return store.Streams{}.RecordDelivery(ctx, sess, id, at, deliveryErr)
	})
}

// MarkFailed implements Subscriptions.
func (s Stored) MarkFailed(ctx context.Context, ws scope.Workspace, id string) error {
	return s.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		return store.Streams{}.MarkSubscriptionFailed(ctx, sess, id)
	})
}

// Remove implements Subscriptions.
func (s Stored) Remove(ctx context.Context, ws scope.Workspace, owner string, sub domain.Subscription) error {
	return s.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		gone, err := store.Streams{}.DeleteExternalSubscription(ctx, sess, sub.ID)
		if err != nil || !gone {
			return err
		}
		if err := service.SubscriptionsChangedNotice(ctx, sess, owner, sub.StreamID); err != nil {
			return err
		}
		if sub.SecretName == nil || *sub.SecretName == "" {
			return nil
		}
		_, err = s.Secrets.Manager(sess, owner).Delete(ctx, *sub.SecretName)
		return err
	})
}

// Expired implements Subscriptions.
func (s Stored) Expired(ctx context.Context) ([]domain.Subscription, error) {
	q, release, err := s.DB.Global().Read(ctx)
	if err != nil {
		return nil, err
	}
	defer release()
	return store.Polling{}.ExpiredExternalSubscriptions(ctx, q)
}
