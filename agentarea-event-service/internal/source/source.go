// Package source reads the stream sources the event service acts on and
// writes back what it learned: the poll cursor, the last error, the URL it
// registered.
package source

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"log/slog"

	"github.com/agentarea/event-service/internal/catalog"
)

// Kinds of stream_sources rows.
const (
	KindWebhook = "webhook"
	KindPoll    = "poll"
)

// Source is one stream_sources row with its catalog entry.
type Source struct {
	ID            string
	WorkspaceID   string
	Kind          string
	Slug          string
	WebhookID     string
	CredentialKey string
	Config        map[string]any
	Cursor        string
	RegisteredURL string
	Entry         catalog.Entry
	// EntrySpec is the entry as stored, to tell when it changed.
	EntrySpec string
}

// WebhookURL is where the provider sends a webhook source's events.
func (s Source) WebhookURL(apiURL string) string {
	if s.WebhookID == "" {
		return ""
	}
	return apiURL + "/webhooks/" + s.WebhookID
}

// Store reads and writes stream_sources.
type Store struct {
	db *sql.DB
}

// NewStore wraps the platform database.
func NewStore(db *sql.DB) *Store {
	return &Store{db: db}
}

// The entry of the source's type from the highest-priority active registry,
// as the platform's CatalogSourceTypeRepository picks it; the catalog is global.
const loadQuery = `
SELECT s.id::text, s.workspace_id, s.kind, s.webhook_type,
       COALESCE(s.webhook_id, ''), COALESCE(s.credential_key::text, ''),
       COALESCE(s.webhook_config::text, 'null'), COALESCE(s.poll_cursor, ''),
       COALESCE(s.registered_url, ''), e.spec::text
FROM stream_sources s
JOIN LATERAL (
    SELECT ri.spec
    FROM registry_items ri
    WHERE ri.registry_type = 'source_types' AND ri.registry_active
      AND ri.external_id = s.webhook_type
    ORDER BY ri.registry_priority
    LIMIT 1
) e ON true
WHERE s.kind = 'poll'
   OR (s.kind = 'webhook' AND jsonb_typeof(e.spec->'registration') = 'object')
ORDER BY s.created_at`

// Load returns every poll source and every webhook source whose entry
// registers with its provider. A row whose entry cannot be read is logged and
// left out: one bad entry must not stop every other source.
func (s *Store) Load(ctx context.Context) ([]Source, error) {
	rows, err := s.db.QueryContext(ctx, loadQuery)
	if err != nil {
		return nil, fmt.Errorf("load stream sources: %w", err)
	}
	defer rows.Close()

	var sources []Source
	for rows.Next() {
		var src Source
		var config string
		if err := rows.Scan(&src.ID, &src.WorkspaceID, &src.Kind, &src.Slug, &src.WebhookID,
			&src.CredentialKey, &config, &src.Cursor, &src.RegisteredURL, &src.EntrySpec); err != nil {
			return nil, fmt.Errorf("scan stream source: %w", err)
		}
		if err := json.Unmarshal([]byte(config), &src.Config); err != nil {
			slog.Error("stream source config is not JSON, skipping", "source_id", src.ID, "error", err)
			continue
		}
		entry, err := catalog.Parse([]byte(src.EntrySpec))
		if err != nil {
			slog.Error("source type entry cannot be read, skipping", "source_id", src.ID, "slug", src.Slug, "error", err)
			continue
		}
		src.Entry = entry
		sources = append(sources, src)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate stream sources: %w", err)
	}
	return sources, nil
}

// Polled records a successful poll; cursor "" keeps the stored one.
func (s *Store) Polled(ctx context.Context, sourceID, cursor string) error {
	_, err := s.db.ExecContext(ctx, `
UPDATE stream_sources
SET poll_cursor = COALESCE(NULLIF($2, ''), poll_cursor), polled_at = now(), poll_error = NULL
WHERE id = $1::uuid`, sourceID, cursor)
	if err != nil {
		return fmt.Errorf("record poll of %s: %w", sourceID, err)
	}
	return nil
}

// Failed records why the last poll or registration of a source failed.
func (s *Store) Failed(ctx context.Context, sourceID, reason string) error {
	_, err := s.db.ExecContext(ctx, `
UPDATE stream_sources SET polled_at = now(), poll_error = $2 WHERE id = $1::uuid`, sourceID, reason)
	if err != nil {
		return fmt.Errorf("record failure of %s: %w", sourceID, err)
	}
	return nil
}

// Registered records the webhook URL now registered with the provider; ""
// records that none is.
func (s *Store) Registered(ctx context.Context, sourceID, url string) error {
	_, err := s.db.ExecContext(ctx, `
UPDATE stream_sources SET registered_url = NULLIF($2, ''), poll_error = NULL WHERE id = $1::uuid`, sourceID, url)
	if err != nil {
		return fmt.Errorf("record registration of %s: %w", sourceID, err)
	}
	return nil
}
