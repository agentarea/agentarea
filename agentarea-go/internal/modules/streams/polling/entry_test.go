package polling

import (
	"context"
	"encoding/json"
	"log/slog"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
)

type rows []catalogapi.SourceTypeRow

func (r rows) SourceTypeRows(context.Context) ([]catalogapi.SourceTypeRow, error) { return r, nil }
func (r rows) SourceTypeRowsBySlug(context.Context, string) ([]catalogapi.SourceTypeRow, error) {
	return r, nil
}

// shippedSourceTypes is data/catalog/source-types.json, the entries the catalog ships.
func shippedSourceTypes(t *testing.T) rows {
	t.Helper()
	_, here, _, _ := runtime.Caller(0)
	path := filepath.Join(filepath.Dir(here), "../../../../../data/catalog/source-types.json")
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("shipped catalog %s: %v", path, err)
	}
	var doc struct {
		SourceTypes []json.RawMessage `json:"source_types"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatalf("source-types.json: %v", err)
	}
	var out rows
	for _, spec := range doc.SourceTypes {
		var head struct {
			Slug string `json:"slug"`
		}
		if err := json.Unmarshal(spec, &head); err != nil {
			t.Fatal(err)
		}
		out = append(out, catalogapi.SourceTypeRow{Slug: head.Slug, Spec: spec})
	}
	return out
}

func TestTheShippedPollEntriesReachThePollers(t *testing.T) {
	entries, err := CatalogEntries(shippedSourceTypes(t), slog.Default())(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	tg, ok := entries["telegram"]
	if !ok || tg.Entry.Poll == nil || tg.Entry.Poll.Transport != HTTPJSON || tg.Entry.Poll.Items != "result" ||
		tg.Entry.Poll.Cursor != "{item:update_id}+1" || tg.Entry.Registration == nil || tg.Entry.Registration.Register == nil {
		t.Fatalf("telegram = %+v", tg.Entry)
	}
	if _, err := tg.Entry.Poll.PollInterval(); err != nil {
		t.Fatalf("telegram interval: %v", err)
	}
	if rss := entries["rss"]; rss.Entry.Poll == nil || rss.Entry.Poll.Transport != Feed {
		t.Fatalf("rss = %+v", rss.Entry)
	}
	if mail := entries["imap"]; mail.Entry.Poll == nil || mail.Entry.Poll.IMAP["host"] == "" {
		t.Fatalf("imap = %+v", mail.Entry)
	}
	if mcp := entries["mcp_events"]; mcp.Entry.Registration == nil || mcp.Entry.Registration.Transport != MCPEvents {
		t.Fatalf("mcp_events = %+v", mcp.Entry)
	}
}

func TestTheFirstValidEntryOfASlugWins(t *testing.T) {
	r := rows{
		{Slug: "feedy", Spec: json.RawMessage(`{"slug":"feedy","name":"F","delivery":"carrier","event":{"kind":"item"}}`)},
		{Slug: "feedy", Spec: json.RawMessage(`{"slug":"feedy","name":"F","delivery":"poll","event":{"kind":"item"},"poll":{"transport":"feed","request":{"url":"{config.url}"}}}`)},
		{Slug: "feedy", Spec: json.RawMessage(`{"slug":"feedy","name":"F","delivery":"poll","event":{"kind":"item"},"poll":{"transport":"imap"}}`)},
	}
	entries, err := CatalogEntries(r, slog.Default())(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	e := entries["feedy"]
	if e.Entry.Poll == nil || e.Entry.Poll.Transport != Feed || e.Entry.Poll.Interval != "60s" || e.Entry.Poll.Request.Method != "GET" {
		t.Fatalf("entry = %+v", e.Entry.Poll)
	}
}
