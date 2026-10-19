package transport

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/agentarea/event-service/internal/catalog"
	"github.com/agentarea/event-service/internal/template"
)

const rss = `<?xml version="1.0"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
<item><guid>n3</guid><title>Third</title><link>https://x/3</link><pubDate>Wed, 15 Oct 2026 10:00:00 GMT</pubDate><description>c</description><dc:creator>ann</dc:creator></item>
<item><guid>n2</guid><title>Second</title><link>https://x/2</link></item>
<item><title>First</title><link>https://x/1</link></item>
</channel></rss>`

const atom = `<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>tag:x,1</id><title type="text">Hello</title><link rel="alternate" href="https://x/a"/><updated>2026-10-15T10:00:00Z</updated><summary>s</summary><author><name>bob</name></author></entry>
</feed>`

func TestParseFeedReadsRSS(t *testing.T) {
	items, err := ParseFeed([]byte(rss))
	if err != nil {
		t.Fatalf("ParseFeed: %v", err)
	}
	if len(items) != 3 {
		t.Fatalf("items = %d", len(items))
	}
	if items[0]["id"] != "n3" || items[0]["author"] != "ann" || items[0]["summary"] != "c" {
		t.Fatalf("first = %v", items[0])
	}
	if items[2]["id"] != "https://x/1" {
		t.Fatalf("an item without a guid is not keyed by its link: %v", items[2])
	}
}

func TestParseFeedReadsAtom(t *testing.T) {
	items, err := ParseFeed([]byte(atom))
	if err != nil {
		t.Fatalf("ParseFeed: %v", err)
	}
	if len(items) != 1 || items[0]["id"] != "tag:x,1" || items[0]["link"] != "https://x/a" ||
		items[0]["title"] != "Hello" || items[0]["author"] != "bob" || items[0]["updated"] != "2026-10-15T10:00:00Z" {
		t.Fatalf("items = %v", items)
	}
}

func TestParseFeedRefusesHTML(t *testing.T) {
	if _, err := ParseFeed([]byte(`<html><body>nope</body></html>`)); err == nil {
		t.Fatal("parsed an HTML page as a feed")
	}
}

func TestTheFirstFeedPollOnlyRecordsWhatIsThere(t *testing.T) {
	items, _ := ParseFeed([]byte(rss))
	res, err := NewFeedItems(items, "")
	if err != nil {
		t.Fatalf("NewFeedItems: %v", err)
	}
	if len(res.Items) != 0 || res.Cursor != `["n3","n2","https://x/1"]` {
		t.Fatalf("result = %+v", res)
	}
}

func TestAFeedPollReturnsNewItemsOldestFirst(t *testing.T) {
	items, _ := ParseFeed([]byte(rss))
	res, err := NewFeedItems(items, `["https://x/1"]`)
	if err != nil {
		t.Fatalf("NewFeedItems: %v", err)
	}
	if len(res.Items) != 2 || res.Items[0].(map[string]any)["id"] != "n2" || res.Items[1].(map[string]any)["id"] != "n3" {
		t.Fatalf("items = %v", res.Items)
	}
	if res.Gap != "" {
		t.Fatalf("gap = %q", res.Gap)
	}
}

func TestAFeedThatMovedPastEverythingSeenIsAGap(t *testing.T) {
	items, _ := ParseFeed([]byte(rss))
	res, err := NewFeedItems(items, `["n0"]`)
	if err != nil {
		t.Fatalf("NewFeedItems: %v", err)
	}
	if len(res.Items) != 3 || res.Gap == "" {
		t.Fatalf("result = %+v", res)
	}
}

func TestFeedTransportFetches(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(atom))
	}))
	defer server.Close()

	tr, _ := NewSet(openPolicy(t)).Get(Feed)
	res, err := tr.Fetch(context.Background(), Fetch{
		Poll:   catalog.Poll{Transport: Feed, Request: &catalog.Request{URL: "{config.url}"}},
		Values: template.Values{Config: map[string]any{"url": server.URL}, Cursor: `["old"]`},
	})
	if err != nil {
		t.Fatalf("Fetch: %v", err)
	}
	if len(res.Items) != 1 {
		t.Fatalf("items = %v", res.Items)
	}
}
