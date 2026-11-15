package partitions

import (
	"compress/gzip"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store"
)

const archiveBatch = 500

// ArchiveKey is where one workspace's events of day go: quote(workspace_id, safe=”).
func ArchiveKey(workspaceID string, day time.Time) string {
	ws := strings.ReplaceAll(url.QueryEscape(workspaceID), "+", "%20")
	return "event-archive/" + ws + "/" + day.UTC().Format(time.DateOnly) + ".jsonl.gz"
}

// archiveLine is RoutedEvent.model_dump_json(): the CloudEvents envelope, the stream attributes,
// the read model's position and routing tally.
type archiveLine struct {
	ID              string              `json:"id"`
	Type            string              `json:"type"`
	Source          string              `json:"source"`
	Time            time.Time           `json:"time"`
	SpecVersion     string              `json:"specversion"`
	DataContentType string              `json:"datacontenttype"`
	Subject         *string             `json:"subject"`
	CorrelationID   *string             `json:"correlation_id"`
	CausationID     *string             `json:"causation_id"`
	TraceParent     *string             `json:"traceparent"`
	Data            map[string]any      `json:"data"`
	Extensions      map[string]string   `json:"extensions"`
	StreamID        string              `json:"stream_id"`
	WorkspaceID     string              `json:"workspace_id"`
	CreatedBy       string              `json:"created_by"`
	EventKey        string              `json:"event_key"`
	ReceivedAt      time.Time           `json:"received_at"`
	Depth           int                 `json:"depth"`
	SourceID        *string             `json:"source_id"`
	SourceType      *string             `json:"source_type"`
	SessionKey      *string             `json:"session_key"`
	Sender          *string             `json:"sender"`
	Attachments     []domain.Attachment `json:"attachments"`
	Sequence        int64               `json:"sequence"`
	RoutedAt        *time.Time          `json:"routed_at"`
	Subscribers     *int                `json:"subscribers"`
	Reacted         int                 `json:"reacted"`
	Skipped         int                 `json:"skipped"`
	Errors          int                 `json:"errors"`
}

func lineOf(e domain.RecordedEvent) archiveLine {
	data := e.Data
	if data == nil {
		data = map[string]any{}
	}
	atts := e.Attachments
	if atts == nil {
		atts = []domain.Attachment{}
	}
	return archiveLine{
		ID: e.ID, Type: e.Kind, Source: e.Source, Time: e.OccurredAt, SpecVersion: "1.0", DataContentType: "application/json",
		Subject: e.Subject, CorrelationID: e.CorrelationID, CausationID: e.CausationID, Data: data, Extensions: map[string]string{},
		StreamID: e.StreamID, WorkspaceID: e.WorkspaceID, CreatedBy: e.CreatedBy, EventKey: e.EventKey, ReceivedAt: e.ReceivedAt,
		Depth: e.Depth, SourceID: e.SourceID, SourceType: e.SourceType, SessionKey: e.SessionKey, Sender: e.Sender,
		Attachments: atts, Sequence: e.Sequence, RoutedAt: e.RoutedAt, Subscribers: e.Subscribers,
		Reacted: e.Reacted, Skipped: e.Skipped, Errors: e.Errors,
	}
}

// spool is one workspace's events of a day, gzipped JSONL in a temporary file until stored.
type spool struct {
	workspaceID string
	file        *os.File
	gz          *gzip.Writer
	enc         *json.Encoder
}

func newSpool(workspaceID string) (*spool, error) {
	f, err := os.CreateTemp("", "event-archive-*.jsonl.gz")
	if err != nil {
		return nil, err
	}
	gz := gzip.NewWriter(f)
	return &spool{workspaceID: workspaceID, file: f, gz: gz, enc: json.NewEncoder(gz)}, nil
}

func (s *spool) write(e domain.RecordedEvent) error { return s.enc.Encode(lineOf(e)) }

func (s *spool) store(ctx context.Context, archive Archive, day time.Time) (string, error) {
	key := ArchiveKey(s.workspaceID, day)
	if err := s.gz.Close(); err != nil {
		return "", err
	}
	if _, err := s.file.Seek(0, io.SeekStart); err != nil {
		return "", err
	}
	return key, archive.Put(ctx, key, s.file, -1, blob.PutOptions{ContentType: "application/gzip"})
}

func (s *spool) close() error {
	return errors.Join(s.file.Close(), os.Remove(s.file.Name()))
}

func (m *Maintainer) writeArchive(ctx context.Context, day time.Time) (keys []string, err error) {
	var sp *spool
	defer func() {
		if sp != nil {
			err = errors.Join(err, sp.close())
		}
	}()
	flush := func() error {
		key, err := sp.store(ctx, m.d.Archive, day)
		err = errors.Join(err, sp.close())
		sp = nil
		if err == nil {
			keys = append(keys, key)
		}
		return err
	}
	var after *store.EventCursor
	for {
		q, release, err := m.d.DB.Global().Read(ctx)
		if err != nil {
			return keys, err
		}
		page, err := m.st.EventsOfDay(ctx, q, day, after, archiveBatch)
		release()
		if err != nil {
			return keys, err
		}
		for _, e := range page {
			if sp != nil && sp.workspaceID != e.WorkspaceID {
				if err := flush(); err != nil {
					return keys, err
				}
			}
			if sp == nil {
				if sp, err = newSpool(e.WorkspaceID); err != nil {
					return keys, err
				}
			}
			if err := sp.write(e); err != nil {
				return keys, err
			}
		}
		if len(page) < archiveBatch {
			break
		}
		last := page[len(page)-1]
		after = &store.EventCursor{WorkspaceID: last.WorkspaceID, Sequence: last.Sequence}
	}
	if sp != nil {
		return keys, flush()
	}
	return keys, nil
}
