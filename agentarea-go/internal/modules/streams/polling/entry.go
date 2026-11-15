package polling

import (
	"context"
	"log/slog"

	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
)

// CatalogEntries reads the entries from the catalog's source types: the first valid entry of
// each slug, by registry priority. An invalid entry is logged and skipped, as the API does.
func CatalogEntries(types catalogapi.SourceTypes, log *slog.Logger) Entries {
	return func(ctx context.Context) (map[string]EntryOf, error) {
		rows, err := types.SourceTypeRows(ctx)
		if err != nil {
			return nil, err
		}
		out := make(map[string]EntryOf, len(rows))
		for _, r := range rows {
			if _, ok := out[r.Slug]; ok {
				continue
			}
			e, err := domain.ParseSourceTypeEntry(r.Spec)
			if err != nil {
				log.ErrorContext(ctx, "Catalog source type is not a valid entry", "slug", r.Slug, "error", err)
				continue
			}
			out[r.Slug] = EntryOf{Entry: EntryFrom(e), Spec: string(r.Spec)}
		}
		return out, nil
	}
}

// EntryFrom is the part of a catalog entry the pollers act on.
func EntryFrom(e domain.SourceTypeEntry) Entry {
	out := Entry{Slug: e.Slug}
	if p := e.Poll; p != nil {
		out.Poll = &Poll{
			Transport: p.Transport, Request: requestFrom(p.Request), Items: deref(p.Items),
			Cursor: deref(p.Cursor), Interval: p.Interval, IMAP: p.IMAP,
		}
	}
	if r := e.Registration; r != nil {
		out.Registration = &Registration{
			Register: requestFrom(r.Register), Unregister: requestFrom(r.Unregister), Transport: deref(r.Transport),
		}
	}
	return out
}

func requestFrom(r *domain.Request) *Request {
	if r == nil {
		return nil
	}
	return &Request{Method: r.Method, URL: r.URL, Headers: r.Headers, JSON: r.JSON}
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}
