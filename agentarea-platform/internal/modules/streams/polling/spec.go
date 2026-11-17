package polling

import (
	"fmt"
	"time"
)

// Transport names a poll block may use.
const (
	HTTPJSON  = "http_json"
	Feed      = "feed"
	IMAP      = "imap"
	MCPEvents = "mcp_events"
)

// DefaultPollInterval is the wait when an entry names none.
const DefaultPollInterval = 60 * time.Second

// Request is an outbound HTTP call described by templates.
type Request struct {
	Method  string
	URL     string
	Headers map[string]string
	JSON    any
}

// Poll is how a poll source is fetched.
type Poll struct {
	Transport string
	Request   *Request
	Items     string
	Cursor    string
	Interval  string
	// IMAP holds the templates of host, port, use_ssl, mailbox, username and password.
	IMAP map[string]string
}

// Registration points a provider at a webhook source's URL: two templated requests, or a
// protocol of its own (mcp_events).
type Registration struct {
	Register   *Request
	Unregister *Request
	Transport  string
}

// Entry is what the pollers act on of a source type's catalog entry.
type Entry struct {
	Slug         string
	Poll         *Poll
	Registration *Registration
}

// PollInterval is the wait between two polls; zero polls again at once (a long poll waits
// at the provider).
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
