//go:build suite

package harness

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"
)

// Event is one server-sent event.
type Event struct {
	ID    string
	Event string
	Data  string
	Retry string
}

// Stream reads a text/event-stream reply.
type Stream struct {
	Status int
	Header http.Header

	t      testing.TB
	cancel context.CancelFunc
	body   io.ReadCloser
	events chan Event
	err    chan error
}

// Stream opens an SSE route. It fails the test unless the reply is 200
// text/event-stream; within bounds the whole read, after which the stream
// is closed. Close is registered with t.Cleanup.
func (c *Client) Stream(t testing.TB, path string, within time.Duration) *Stream {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), within)
	req := c.newRequest(t, Request{Method: http.MethodGet, Path: path})
	req = req.WithContext(ctx)
	req.Header.Set("Accept", "text/event-stream")
	streaming := &http.Client{CheckRedirect: c.http.CheckRedirect}
	resp, err := streaming.Do(req)
	if err != nil {
		cancel()
		t.Fatalf("%s GET %s (stream): %v", c.Name, path, err)
	}
	ct, _, _ := strings.Cut(resp.Header.Get("Content-Type"), ";")
	if resp.StatusCode != http.StatusOK || strings.TrimSpace(ct) != "text/event-stream" {
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 4000))
		_ = resp.Body.Close()
		cancel()
		t.Fatalf("%s GET %s (stream): status %d content-type %q: %s", c.Name, path, resp.StatusCode, ct, raw)
	}
	s := &Stream{
		Status: resp.StatusCode, Header: resp.Header,
		t: t, cancel: cancel, body: resp.Body,
		events: make(chan Event, 64), err: make(chan error, 1),
	}
	go s.read()
	t.Cleanup(s.Close)
	return s
}

func (s *Stream) read() {
	defer close(s.events)
	sc := bufio.NewScanner(s.body)
	sc.Buffer(make([]byte, 64*1024), 8*1024*1024)
	var ev Event
	var data []string
	pending := false
	for sc.Scan() {
		line := strings.TrimSuffix(sc.Text(), "\r")
		if line == "" {
			if pending {
				ev.Data = strings.Join(data, "\n")
				s.events <- ev
			}
			ev, data, pending = Event{}, nil, false
			continue
		}
		if strings.HasPrefix(line, ":") {
			continue
		}
		field, value, _ := strings.Cut(line, ":")
		value = strings.TrimPrefix(value, " ")
		switch field {
		case "data":
			data = append(data, value)
			pending = true
		case "event":
			ev.Event, pending = value, true
		case "id":
			ev.ID, pending = value, true
		case "retry":
			ev.Retry, pending = value, true
		}
	}
	if err := sc.Err(); err != nil && !errors.Is(err, context.Canceled) && !errors.Is(err, context.DeadlineExceeded) {
		s.err <- err
	}
}

// Next returns the next event, or fails the test when none arrives within d
// or the stream ends.
func (s *Stream) Next(d time.Duration) Event {
	s.t.Helper()
	ev, err := s.TryNext(d)
	if err != nil {
		s.t.Fatal(err)
	}
	return ev
}

// TryNext is Next returning the failure instead; io.EOF means the server
// closed the stream.
func (s *Stream) TryNext(d time.Duration) (Event, error) {
	timer := time.NewTimer(d)
	defer timer.Stop()
	select {
	case ev, ok := <-s.events:
		if !ok {
			select {
			case err := <-s.err:
				return Event{}, fmt.Errorf("stream failed: %w", err)
			default:
				return Event{}, io.EOF
			}
		}
		return ev, nil
	case <-timer.C:
		return Event{}, fmt.Errorf("no event within %s", d)
	}
}

// Take reads n events, each within d.
func (s *Stream) Take(n int, d time.Duration) []Event {
	s.t.Helper()
	out := make([]Event, 0, n)
	for range n {
		out = append(out, s.Next(d))
	}
	return out
}

// Until reads events until match returns true for one, within d overall,
// and returns every event read, the matching one last.
func (s *Stream) Until(d time.Duration, match func(Event) bool) []Event {
	s.t.Helper()
	deadline := time.Now().Add(d)
	var out []Event
	for {
		left := time.Until(deadline)
		if left <= 0 {
			s.t.Fatalf("no matching event within %s; read %d events", d, len(out))
		}
		ev := s.Next(left)
		out = append(out, ev)
		if match(ev) {
			return out
		}
	}
}

// Close ends the stream.
func (s *Stream) Close() {
	s.cancel()
	_ = s.body.Close()
}
