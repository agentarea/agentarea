// Package catalog holds the parts of a source type catalog entry the event
// service acts on: how to poll it and how to register a webhook with it.
package catalog

import (
	"encoding/json"
	"fmt"
	"time"
)

// Request is an outbound HTTP call described by templates.
type Request struct {
	Method  string            `json:"method"`
	URL     string            `json:"url"`
	Headers map[string]string `json:"headers,omitempty"`
	JSON    any               `json:"json,omitempty"`
}

// IMAP names, as templates, where a mailbox is and who logs in.
type IMAP struct {
	Host     string `json:"host"`
	Port     string `json:"port,omitempty"`
	UseSSL   string `json:"use_ssl,omitempty"`
	Mailbox  string `json:"mailbox,omitempty"`
	Username string `json:"username"`
	Password string `json:"password"`
}

// Poll is how the event service fetches a poll source.
type Poll struct {
	Transport string   `json:"transport"`
	Request   *Request `json:"request,omitempty"`
	Items     string   `json:"items,omitempty"`
	Cursor    string   `json:"cursor,omitempty"`
	Interval  string   `json:"interval,omitempty"`
	IMAP      *IMAP    `json:"imap,omitempty"`
}

// Registration registers a source's webhook URL with its provider.
type Registration struct {
	Register   *Request `json:"register,omitempty"`
	Unregister *Request `json:"unregister,omitempty"`
}

// Entry is a source type catalog entry, read from registry_items.spec.
type Entry struct {
	Slug         string        `json:"slug"`
	Poll         *Poll         `json:"poll,omitempty"`
	Registration *Registration `json:"registration,omitempty"`
}

// Parse reads an entry from its stored JSON.
func Parse(spec []byte) (Entry, error) {
	var entry Entry
	if err := json.Unmarshal(spec, &entry); err != nil {
		return Entry{}, fmt.Errorf("parse source type entry: %w", err)
	}
	if entry.Slug == "" {
		return Entry{}, fmt.Errorf("source type entry has no slug")
	}
	return entry, nil
}

// DefaultPollInterval is the wait when an entry names none, as the platform's
// catalog model defaults it.
const DefaultPollInterval = 60 * time.Second

// PollInterval is the wait between two polls; zero means poll again at once
// (a long poll waits at the provider).
func (p Poll) PollInterval() (time.Duration, error) {
	if p.Interval == "" {
		return DefaultPollInterval, nil
	}
	d, err := time.ParseDuration(p.Interval)
	if err != nil {
		return 0, fmt.Errorf("poll interval %q: %w", p.Interval, err)
	}
	if d < 0 {
		return 0, fmt.Errorf("poll interval %q is negative", p.Interval)
	}
	return d, nil
}
