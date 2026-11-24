package httpx

import (
	"context"
	"errors"
	"net/http"
	"sync"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
)

// SSEHeartbeat is how long a feed may be silent before a ": ping" comment
// (agents_tasks.py _with_sse_heartbeats).
const SSEHeartbeat = 15 * time.Second

// SSEPing is the heartbeat frame.
const SSEPing = ": ping\n\n"

// FormatSSE is a frame as _format_sse_event writes it: "id:" only for a
// non-empty id, the data as json.dumps with its defaults (ASCII escapes,
// ", " and ": "). Use wirejson.Object and wirejson.Float for the key order and
// floats Python writes.
func FormatSSE(eventType string, data any, id string) ([]byte, error) {
	body, err := wirejson.Marshal(data, wirejson.Dumps)
	if err != nil {
		return nil, err
	}
	out := make([]byte, 0, len(body)+len(eventType)+len(id)+24)
	if id != "" {
		out = append(out, "id: "...)
		out = append(out, id...)
		out = append(out, '\n')
	}
	out = append(out, "event: "...)
	out = append(out, eventType...)
	out = append(out, "\ndata: "...)
	out = append(out, body...)
	return append(out, '\n', '\n'), nil
}

// SSEComment is a comment frame (": subscribed\n\n").
func SSEComment(text string) []byte { return []byte(": " + text + "\n\n") }

// LastEventID is the id the reconnecting client last saw.
func LastEventID(r *http.Request) string { return r.Header.Get("Last-Event-ID") }

// SSE writes one event stream.
type SSE struct {
	w  http.ResponseWriter
	rc *http.ResponseController
	mu sync.Mutex
}

// StartSSE answers 200 with the headers the Python streams send
// (StreamingResponse, media type text/event-stream) and flushes them.
func StartSSE(w http.ResponseWriter, r *http.Request) (*SSE, error) {
	h := w.Header()
	h.Set("Content-Type", "text/event-stream; charset=utf-8")
	h.Set("Cache-Control", "no-cache")
	if r.ProtoMajor == 1 {
		h.Set("Connection", "keep-alive")
	}
	w.WriteHeader(http.StatusOK)
	s := &SSE{w: w, rc: http.NewResponseController(w)}
	if err := s.rc.Flush(); err != nil && !errors.Is(err, http.ErrNotSupported) {
		return nil, err
	}
	return s, nil
}

// Write sends one frame and flushes it.
func (s *SSE) Write(frame []byte) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, err := s.w.Write(frame); err != nil {
		return err
	}
	if err := s.rc.Flush(); err != nil && !errors.Is(err, http.ErrNotSupported) {
		return err
	}
	return nil
}

// Event formats and sends one event.
func (s *SSE) Event(eventType string, data any, id string) error {
	frame, err := FormatSSE(eventType, data, id)
	if err != nil {
		return err
	}
	return s.Write(frame)
}

// Pump writes frames as they come and a ping after every interval without
// one, until frames is closed (nil) or ctx ends (its error). A failed write
// (the client left) is returned.
func (s *SSE) Pump(ctx context.Context, frames <-chan []byte, interval time.Duration) error {
	timer := time.NewTimer(interval)
	defer timer.Stop()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case frame, ok := <-frames:
			if !ok {
				return nil
			}
			if err := s.Write(frame); err != nil {
				return err
			}
		case <-timer.C:
			if err := s.Write([]byte(SSEPing)); err != nil {
				return err
			}
		}
		if !timer.Stop() {
			select {
			case <-timer.C:
			default:
			}
		}
		timer.Reset(interval)
	}
}
