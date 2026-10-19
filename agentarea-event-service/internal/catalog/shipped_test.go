package catalog_test

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/agentarea/event-service/internal/catalog"
	"github.com/agentarea/event-service/internal/template"
	"github.com/agentarea/event-service/internal/transport"
)

// The shipped catalog, as the platform reconciles it into registry_items.
var shippedCatalog = filepath.Join("..", "..", "..", "data", "catalog", "source-types.json")

type field struct {
	Key string `json:"key"`
}

type shippedEntry struct {
	Slug        string          `json:"slug"`
	Delivery    string          `json:"delivery"`
	Credentials []field         `json:"credentials"`
	Config      []field         `json:"config"`
	Raw         json.RawMessage `json:"-"`
}

func shippedEntries(t *testing.T) []shippedEntry {
	t.Helper()
	data, err := os.ReadFile(shippedCatalog)
	if err != nil {
		t.Fatalf("read %s: %v", shippedCatalog, err)
	}
	var doc struct {
		SourceTypes []json.RawMessage `json:"source_types"`
	}
	if err := json.Unmarshal(data, &doc); err != nil {
		t.Fatalf("decode catalog: %v", err)
	}
	entries := make([]shippedEntry, 0, len(doc.SourceTypes))
	for _, raw := range doc.SourceTypes {
		var e shippedEntry
		if err := json.Unmarshal(raw, &e); err != nil {
			t.Fatalf("decode entry: %v", err)
		}
		e.Raw = raw
		entries = append(entries, e)
	}
	if len(entries) == 0 {
		t.Fatal("the shipped catalog has no entries")
	}
	return entries
}

// Values a configured source of the entry would have: every credential and
// config field filled in, as the platform stores them.
func sampleValues(e shippedEntry, cursor string) template.Values {
	credentials := map[string]string{}
	for _, f := range e.Credentials {
		credentials[f.Key] = f.Key + "-value"
	}
	config := map[string]any{}
	for _, f := range e.Config {
		config[f.Key] = f.Key + "-value"
	}
	if _, ok := config["port"]; ok {
		config["port"] = float64(993)
	}
	if _, ok := config["use_ssl"]; ok {
		config["use_ssl"] = true
	}
	if _, ok := config["url"]; ok {
		config["url"] = "https://example.com/feed.xml"
	}
	return template.Values{
		Credentials: credentials,
		Config:      config,
		Cursor:      cursor,
		WebhookURL:  "https://api.example.com/v1/webhooks/9b6b1d5e",
		SourceID:    "9b6b1d5e-0b0d-4d6b-8b8a-2d0e5f6a7b8c",
	}
}

func renderRequest(t *testing.T, slug, what string, req *catalog.Request, v template.Values) {
	t.Helper()
	if _, err := template.Render(req.URL, v); err != nil {
		t.Errorf("%s %s url: %v", slug, what, err)
	}
	for name, tmpl := range req.Headers {
		if _, err := template.Render(tmpl, v); err != nil {
			t.Errorf("%s %s header %s: %v", slug, what, name, err)
		}
	}
	if req.JSON == nil {
		return
	}
	rendered, err := template.RenderJSON(req.JSON, v)
	if err != nil {
		t.Errorf("%s %s body: %v", slug, what, err)
		return
	}
	want, _ := req.JSON.(map[string]any)
	got, _ := rendered.(map[string]any)
	if len(got) != len(want) {
		t.Errorf("%s %s body = %v, want every member of %v", slug, what, rendered, req.JSON)
	}
}

func TestEveryShippedEntryParses(t *testing.T) {
	for _, e := range shippedEntries(t) {
		entry, err := catalog.Parse(e.Raw)
		if err != nil {
			t.Errorf("%s: %v", e.Slug, err)
			continue
		}
		polled := e.Delivery == "poll" || e.Delivery == "both"
		if polled != (entry.Poll != nil) {
			t.Errorf("%s: delivery %q but poll block present=%v", e.Slug, e.Delivery, entry.Poll != nil)
		}
		if entry.Poll != nil {
			if _, err := entry.Poll.PollInterval(); err != nil {
				t.Errorf("%s interval: %v", e.Slug, err)
			}
		}
	}
}

func TestShippedPollTemplatesRender(t *testing.T) {
	for _, e := range shippedEntries(t) {
		entry, err := catalog.Parse(e.Raw)
		if err != nil || entry.Poll == nil {
			continue
		}
		poll := entry.Poll
		for _, cursor := range []string{"", "81235"} {
			v := sampleValues(e, cursor)
			switch poll.Transport {
			case "http_json", "feed":
				if poll.Request == nil {
					t.Errorf("%s: %s poll without a request", e.Slug, poll.Transport)
					continue
				}
				renderRequest(t, e.Slug, "poll", poll.Request, v)
			case "imap":
				if poll.IMAP == nil {
					t.Errorf("%s: imap poll without an imap block", e.Slug)
					continue
				}
				if _, err := transport.RenderMailbox(*poll.IMAP, v); err != nil {
					t.Errorf("%s mailbox: %v", e.Slug, err)
				}
			}
		}
		if poll.Cursor != "" {
			item := map[string]any{"update_id": float64(81234), "message": map[string]any{"text": "hi"}}
			next, err := template.RenderCursor(poll.Cursor, item)
			if err != nil || next == "" {
				t.Errorf("%s cursor = %q, %v", e.Slug, next, err)
			}
		}
	}
}

func TestShippedRegistrationTemplatesRender(t *testing.T) {
	for _, e := range shippedEntries(t) {
		entry, err := catalog.Parse(e.Raw)
		if err != nil || entry.Registration == nil {
			continue
		}
		v := sampleValues(e, "")
		if entry.Registration.Register == nil {
			t.Errorf("%s: registration without a register call", e.Slug)
			continue
		}
		renderRequest(t, e.Slug, "register", entry.Registration.Register, v)
		if entry.Registration.Unregister != nil {
			renderRequest(t, e.Slug, "unregister", entry.Registration.Unregister, v)
		}
	}
}
