package polling

import (
	"context"
	"errors"
	"log/slog"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store"
)

// EntryOf is one source type's entry as the pollers read it, and its spec as stored.
type EntryOf struct {
	Entry Entry
	Spec  string
}

// Entries reads the catalog's source types: one entry per slug, from the highest-priority
// active registry, as CatalogSourceTypeRepository picks it.
type Entries func(ctx context.Context) (map[string]EntryOf, error)

// MCPInstances answers whether an MCP server is one of a workspace's (connections' Lookup).
type MCPInstances interface {
	MCPInstanceExists(ctx context.Context, ws scope.Workspace, id string) (bool, error)
}

// StoredSources is Sources over stream_sources, the catalog and connections.
type StoredSources struct {
	DB        db.Database
	Entries   Entries
	Instances MCPInstances
	Now       func() time.Time
	Log       *slog.Logger
}

var _ Sources = StoredSources{}

func (s StoredSources) now() time.Time {
	if s.Now == nil {
		return time.Now()
	}
	return s.Now()
}

func (s StoredSources) write(ctx context.Context, fn func(ctx context.Context, q db.Querier) error) error {
	return s.DB.Global().Write(ctx, fn)
}

// Load returns every poll source and every webhook source whose type registers with its
// provider. A source that cannot be acted on now (config not JSON, type not in the catalog,
// a webhook type that registers nothing) comes back Held: one bad source must not stop every
// other, and a type the catalog lost for a while must not read as a deleted source.
func (s StoredSources) Load(ctx context.Context) ([]Source, error) {
	q, release, err := s.DB.Global().Read(ctx)
	if err != nil {
		return nil, err
	}
	rows, bad, err := store.Polling{}.Sources(ctx, q)
	release()
	if err != nil {
		return nil, err
	}
	out := make([]Source, 0, len(rows)+len(bad))
	for _, e := range bad {
		s.Log.ErrorContext(ctx, "stream source skipped", "error", e)
		if u, ok := errors.AsType[*store.UnreadableSource](e); ok {
			out = append(out, Source{ID: u.ID, Held: true})
		}
	}
	entries, err := s.Entries(ctx)
	if err != nil {
		return nil, err
	}
	for _, r := range rows {
		e, ok := entries[r.Slug]
		if !ok || (r.Kind == KindWebhook && e.Entry.Registration == nil) {
			out = append(out, Source{ID: r.ID, WorkspaceID: r.WorkspaceID, Kind: r.Kind, Slug: r.Slug,
				RegisteredURL: r.RegisteredURL, Held: true})
			continue
		}
		src := Source{
			ID: r.ID, WorkspaceID: r.WorkspaceID, CreatedBy: r.CreatedBy, Kind: r.Kind, Slug: r.Slug,
			WebhookID: r.WebhookID, CredentialKey: r.CredentialKey, Config: r.Config, Cursor: r.Cursor,
			RegisteredURL: r.RegisteredURL, SubscriptionID: r.SubscriptionID, RefreshBefore: r.RefreshBefore,
			PollError: r.PollError, PolledAt: r.PolledAt, Entry: e.Entry, EntrySpec: e.Spec,
		}
		if src.MCPInstanceID, err = s.instance(ctx, r.WorkspaceID, r.Config); err != nil {
			return nil, err
		}
		out = append(out, src)
	}
	return out, nil
}

// instance is the config's mcp_instance_id when that server is one of the source's own
// workspace, "" otherwise.
func (s StoredSources) instance(ctx context.Context, workspaceID string, config map[string]any) (string, error) {
	id, _ := config["mcp_instance_id"].(string)
	if id == "" {
		return "", nil
	}
	ws, err := scope.NewWorkspace(workspaceID, "")
	if err != nil {
		return "", err
	}
	ok, err := s.Instances.MCPInstanceExists(ctx, ws, id)
	if err != nil || !ok {
		return "", err
	}
	return id, nil
}

// Polled implements Sources.
func (s StoredSources) Polled(ctx context.Context, id, cursor string) error {
	return s.write(ctx, func(ctx context.Context, q db.Querier) error {
		return store.Polling{}.Polled(ctx, q, id, cursor, s.now())
	})
}

// Failed implements Sources.
func (s StoredSources) Failed(ctx context.Context, id, reason string) error {
	return s.write(ctx, func(ctx context.Context, q db.Querier) error {
		return store.Polling{}.Failed(ctx, q, id, reason, s.now())
	})
}

// Registered implements Sources.
func (s StoredSources) Registered(ctx context.Context, id, url string) error {
	return s.write(ctx, func(ctx context.Context, q db.Querier) error {
		return store.Polling{}.Registered(ctx, q, id, url)
	})
}

// Unregistered implements Sources.
func (s StoredSources) Unregistered(ctx context.Context, id string) error {
	return s.write(ctx, func(ctx context.Context, q db.Querier) error {
		return store.Polling{}.Unregistered(ctx, q, id)
	})
}

// SubscribeFailed implements Sources.
func (s StoredSources) SubscribeFailed(ctx context.Context, id, reason string, retryIn time.Duration) error {
	if retryIn < 0 {
		return errors.New("negative subscription retry")
	}
	return s.write(ctx, func(ctx context.Context, q db.Querier) error {
		now := s.now()
		return store.Polling{}.SubscribeFailed(ctx, q, id, reason, now, now.Add(retryIn))
	})
}

// Subscribed implements Sources.
func (s StoredSources) Subscribed(ctx context.Context, id, url, subscriptionID string, refreshBefore *time.Time, cursor string) error {
	return s.write(ctx, func(ctx context.Context, q db.Querier) error {
		return store.Polling{}.Subscribed(ctx, q, id, url, subscriptionID, refreshBefore, cursor)
	})
}
