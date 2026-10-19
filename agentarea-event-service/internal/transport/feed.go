package transport

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"encoding/xml"
	"fmt"
	"strings"

	"golang.org/x/net/html/charset"
)

// FeedTransport reads an RSS or Atom document. A feed has no position to ask
// from, so the cursor is the set of item ids the last document held: an item
// not in it is new. The first poll only records that set; a new source starts
// at the feed's present, it does not replay what the feed already shows.
type FeedTransport struct {
	caller *Caller
}

// The cursor keeps at most this many ids, newest documents first.
const maxFeedCursorIDs = 500

// Fetch reads the feed and returns the items not seen before, oldest first.
func (t *FeedTransport) Fetch(ctx context.Context, f Fetch) (Result, error) {
	if f.Poll.Request == nil {
		return Result{}, fmt.Errorf("feed poll has no request")
	}
	data, err := t.caller.Call(ctx, *f.Poll.Request, f.Values)
	if err != nil {
		return Result{}, err
	}
	items, err := ParseFeed(data)
	if err != nil {
		return Result{}, err
	}
	return NewFeedItems(items, f.Values.Cursor)
}

// NewFeedItems compares a document's items with the cursor of the last one.
func NewFeedItems(items []map[string]any, cursor string) (Result, error) {
	ids := make([]string, 0, len(items))
	for _, item := range items {
		ids = append(ids, item["id"].(string))
	}
	next, err := feedCursor(ids)
	if err != nil {
		return Result{}, err
	}
	if cursor == "" {
		return Result{Cursor: next}, nil
	}
	var seen []string
	if err := json.Unmarshal([]byte(cursor), &seen); err != nil {
		return Result{}, fmt.Errorf("feed cursor is not a list of ids: %w", err)
	}
	known := make(map[string]bool, len(seen))
	for _, id := range seen {
		known[id] = true
	}
	var fresh []any
	overlap := false
	for i := len(items) - 1; i >= 0; i-- {
		if known[ids[i]] {
			overlap = true
			continue
		}
		fresh = append(fresh, items[i])
	}
	result := Result{Items: fresh, Cursor: next}
	if len(fresh) > 0 && len(seen) > 0 && !overlap {
		result.Gap = fmt.Sprintf("none of the %d items seen last time is in the feed any more; items published in between may be missing", len(seen))
	}
	return result, nil
}

func feedCursor(ids []string) (string, error) {
	if len(ids) > maxFeedCursorIDs {
		ids = ids[:maxFeedCursorIDs]
	}
	encoded, err := json.Marshal(ids)
	if err != nil {
		return "", fmt.Errorf("feed cursor: %w", err)
	}
	return string(encoded), nil
}

type feedText struct {
	Text  string `xml:",chardata"`
	Inner string `xml:",innerxml"`
}

func (t feedText) String() string {
	if text := strings.TrimSpace(t.Text); text != "" {
		return text
	}
	return strings.TrimSpace(t.Inner)
}

type rssItem struct {
	GUID        string `xml:"guid"`
	About       string `xml:"about,attr"`
	Title       string `xml:"title"`
	Link        string `xml:"link"`
	PubDate     string `xml:"pubDate"`
	Date        string `xml:"http://purl.org/dc/elements/1.1/ date"`
	Description string `xml:"description"`
	Content     string `xml:"http://purl.org/rss/1.0/modules/content/ encoded"`
	Author      string `xml:"author"`
	Creator     string `xml:"http://purl.org/dc/elements/1.1/ creator"`
}

type atomLink struct {
	Href string `xml:"href,attr"`
	Rel  string `xml:"rel,attr"`
}

type atomEntry struct {
	ID        string     `xml:"id"`
	Title     feedText   `xml:"title"`
	Links     []atomLink `xml:"link"`
	Published string     `xml:"published"`
	Updated   string     `xml:"updated"`
	Summary   feedText   `xml:"summary"`
	Content   feedText   `xml:"content"`
	Author    struct {
		Name string `xml:"name"`
	} `xml:"author"`
}

type feedDoc struct {
	XMLName xml.Name
	Channel struct {
		Items []rssItem `xml:"item"`
	} `xml:"channel"`
	// RSS 1.0 keeps its items beside the channel.
	Items   []rssItem   `xml:"item"`
	Entries []atomEntry `xml:"entry"`
}

// ParseFeed reads RSS 2.0, RSS 1.0 or Atom into items of one shape:
// {id, title, link, published, updated, summary, content, author}, in
// document order. id is the guid, else the link.
func ParseFeed(data []byte) ([]map[string]any, error) {
	decoder := xml.NewDecoder(bytes.NewReader(data))
	decoder.CharsetReader = charset.NewReaderLabel
	decoder.Strict = false
	var doc feedDoc
	if err := decoder.Decode(&doc); err != nil {
		return nil, fmt.Errorf("feed is not RSS or Atom XML: %w", err)
	}
	switch strings.ToLower(doc.XMLName.Local) {
	case "rss", "rdf":
	case "feed":
	default:
		return nil, fmt.Errorf("feed root element <%s> is not rss, RDF or feed", doc.XMLName.Local)
	}

	var items []map[string]any
	for _, it := range append(doc.Channel.Items, doc.Items...) {
		published := firstNonEmpty(it.PubDate, it.Date)
		items = append(items, feedItem(
			firstNonEmpty(it.GUID, it.Link, it.About),
			it.Title, it.Link, published, "", it.Description, it.Content,
			firstNonEmpty(it.Author, it.Creator),
		))
	}
	for _, e := range doc.Entries {
		link := ""
		for _, l := range e.Links {
			if l.Rel == "" || l.Rel == "alternate" {
				link = l.Href
				break
			}
		}
		items = append(items, feedItem(
			firstNonEmpty(e.ID, link),
			e.Title.String(), link, e.Published, e.Updated, e.Summary.String(), e.Content.String(),
			e.Author.Name,
		))
	}
	return items, nil
}

func feedItem(id, title, link, published, updated, summary, content, author string) map[string]any {
	id = strings.TrimSpace(id)
	if id == "" {
		sum := sha256.Sum256([]byte(title + "\x00" + published + "\x00" + summary))
		id = "sha256:" + hex.EncodeToString(sum[:])
	}
	return map[string]any{
		"id":        id,
		"title":     strings.TrimSpace(title),
		"link":      strings.TrimSpace(link),
		"published": strings.TrimSpace(published),
		"updated":   strings.TrimSpace(updated),
		"summary":   strings.TrimSpace(summary),
		"content":   strings.TrimSpace(content),
		"author":    strings.TrimSpace(author),
	}
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if strings.TrimSpace(v) != "" {
			return v
		}
	}
	return ""
}
