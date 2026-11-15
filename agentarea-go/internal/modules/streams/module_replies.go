package streams

import (
	"context"
	"errors"
	"fmt"
	"net/http"

	"github.com/redis/go-redis/v9"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/lifecycle"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/replies"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/service"
)

// ReplyDeps are what task reply delivery needs beyond the module's own deps.
type ReplyDeps struct {
	// Redis holds the live Telegram message of each task.
	Redis *redis.Client
	// Dedup is the dedup cache of delivered targets (prefix replies.DedupPrefix, TTL Config.DedupTTL).
	Dedup events.Dedup
	// Consumer names this replica in the delivery group.
	Consumer string
	Config   replies.Config
}

// Replies is the delivery group on tasks.events: every task event to where its task replies
// (its delivery address, its task webhook), and the autoclaimer of what a send left pending.
func (m *Module) Replies(p ReplyDeps) ([]lifecycle.Component, error) {
	switch {
	case m.d.Broker == nil, m.d.TaskOutcomes == nil, m.d.Secrets == nil, m.d.Out == nil, m.d.SourceTypes == nil:
		return nil, errors.New("task reply delivery needs the broker, runs' task reads, secrets, outbound clients and the catalog's source types")
	case p.Redis == nil, p.Dedup == nil:
		return nil, errors.New("task reply delivery needs redis and its dedup cache")
	}
	creds := m.replyCredentials
	vendor := &http.Client{Transport: m.d.Out.Transport(netguard.Vendor)}
	member := &http.Client{
		Transport:     m.d.Out.Transport(netguard.Member),
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
	x, err := replies.New(replies.Deps{
		Broker: m.d.Broker, Dedup: p.Dedup, Tasks: m.d.TaskOutcomes, Consumer: p.Consumer, Config: p.Config,
		Replies: func(ctx context.Context, slug string) (*domain.Reply, bool, error) {
			e, ok, err := m.svc.SourceTypeEntry(ctx, slug)
			return e.Reply, ok, err
		},
		Senders: map[string]replies.Sender{
			"http":          replies.HTTPReply{Credentials: creds, Client: vendor},
			"telegram_live": replies.TelegramLive{Credentials: creds, Redis: p.Redis, Client: vendor},
			"smtp":          replies.Email{Credentials: creds, Dialer: m.d.Out.Dialer()},
			"task_webhook":  replies.TaskWebhook{Secret: m.taskSecret, Client: member, Now: m.d.Now},
		},
		Now: m.d.Now, Log: m.log().With("component", "task reply delivery"),
	})
	if err != nil {
		return nil, err
	}
	return x.Components(), nil
}

// replyCredentials is SourceCredentialReader: the credentials an address sends with, read in
// the task's workspace. A store that does not answer is retried; none stored, or unusable, is final.
func (m *Module) replyCredentials(ctx context.Context, ws scope.Workspace, owner, kind, key string) (map[string]string, error) {
	creds, err := m.svc.SourceCredentials(ctx, ws, owner, kind, key)
	switch {
	case errors.Is(err, service.ErrSecretStoreUnreachable):
		return nil, fmt.Errorf("secret store: %w", err)
	case errors.Is(err, service.ErrCredentialsUnavailable):
		return nil, &replies.Fatal{Msg: err.Error()}
	case err != nil:
		return nil, err
	case len(creds) == 0:
		return nil, &replies.Fatal{Msg: fmt.Sprintf("no credentials for %s source key %s in workspace %s", kind, key, ws.ID())}
	}
	return creds, nil
}

// taskSecret reads a task's secret as its owner, in its workspace.
func (m *Module) taskSecret(ctx context.Context, ws scope.Workspace, owner, name string) (string, bool, error) {
	sess, release, err := m.d.DB.Read(ctx, ws)
	if err != nil {
		return "", false, err
	}
	defer release()
	return readSecret(ctx, m.d.Secrets.Manager(sess, owner), name)
}

func readSecret(ctx context.Context, mgr ksecrets.Manager, name string) (string, bool, error) {
	v, err := mgr.Get(ctx, name)
	if errors.Is(err, ksecrets.ErrNotFound) {
		return "", false, nil
	}
	return v, err == nil, err
}

// TaskEventConsumers are the platform and trigger-outcomes groups on tasks.events: task
// outcomes into each workspace's platform stream, and a fired task's end counted towards its
// trigger. Empty without the subscriber or runs' task reads.
func (m *Module) TaskEventConsumers() []lifecycle.Component {
	if m.d.Subscriber == nil || m.d.TaskOutcomes == nil {
		return nil
	}
	log := m.log()
	return []lifecycle.Component{
		taskEventGroup("tasks-platform-projection", m.d.Subscriber, events.PlatformGroup, m.svc.ProjectTaskEvent,
			func(ctx context.Context, e events.IntegrationEvent) error {
				log.ErrorContext(ctx, "Task event was not projected into the platform stream after the delivery limit; dead-lettered",
					"event_id", e.ID, "type", e.Type, "task_id", e.Subject)
				return nil
			}),
		taskEventGroup("tasks-trigger-outcomes", m.d.Subscriber, events.TriggerOutcomeGroup, m.svc.CountTaskOutcome,
			func(ctx context.Context, e events.IntegrationEvent) error {
				log.ErrorContext(ctx, "The end of a task was not counted towards its trigger after the delivery limit; dead-lettered",
					"event_id", e.ID, "type", e.Type, "task_id", e.Subject)
				return nil
			}),
	}
}

func taskEventGroup(name string, sub events.GroupSubscriber, group string, h, giveUp events.Handler) lifecycle.Component {
	var running events.Subscription
	return lifecycle.Func(name,
		func(ctx context.Context) error {
			s, err := sub.SubscribeMany(context.WithoutCancel(ctx), []string{events.TaskEvents}, group, h,
				events.DeadLetterTopic(events.TaskEvents, group), giveUp)
			if err != nil {
				return err
			}
			running = s
			return nil
		},
		func(ctx context.Context) error {
			if running == nil {
				return nil
			}
			err := running.Stop(ctx)
			running = nil
			if errors.Is(err, context.Canceled) {
				return nil
			}
			return err
		})
}
