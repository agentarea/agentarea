package mcpclient

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"
)

// outbound is a JSON-RPC message the client sends.
type outbound struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      *int64          `json:"id,omitempty"`
	Method  string          `json:"method,omitempty"`
	Params  map[string]any  `json:"params,omitempty"`
	Result  json.RawMessage `json:"result,omitempty"`
	Error   *RPCError       `json:"error,omitempty"`
}

// inbound is a JSON-RPC message the server sends.
type inbound struct {
	ID     json.RawMessage `json:"id,omitempty"`
	Method string          `json:"method,omitempty"`
	Params json.RawMessage `json:"params,omitempty"`
	Result json.RawMessage `json:"result,omitempty"`
	Error  *RPCError       `json:"error,omitempty"`
}

func (m inbound) isResponse() bool { return m.Method == "" && (m.Result != nil || m.Error != nil) }

func (m inbound) idIs(id int64) bool {
	var n json.Number
	dec := json.NewDecoder(bytes.NewReader(m.ID))
	dec.UseNumber()
	if dec.Decode(&n) != nil {
		var s string
		return json.Unmarshal(m.ID, &s) == nil && s == fmt.Sprint(id)
	}
	return n.String() == fmt.Sprint(id)
}

// wire carries messages to one server.
type wire interface {
	// roundTrip sends req and returns its response; notes sees the server's
	// notifications and requests while it waits.
	roundTrip(ctx context.Context, req outbound, h http.Header, notes func(inbound)) (inbound, error)
	// send posts a notification or a response.
	send(ctx context.Context, msg outbound, h http.Header) error
	close()
}

// exchange is the common HTTP part of both wires.
type exchange struct {
	client  *http.Client
	headers http.Header
	idle    time.Duration
}

func newExchange(rt http.RoundTripper, headers http.Header, idle time.Duration) exchange {
	return exchange{
		client: &http.Client{Transport: rt, CheckRedirect: func(*http.Request, []*http.Request) error {
			return http.ErrUseLastResponse
		}},
		headers: headers,
		idle:    idle,
	}
}

// do sends the request; the response must keep arriving within idle, from
// the send to the last byte, or the request is cancelled.
func (x exchange) do(ctx context.Context, method, rawURL string, body []byte, h http.Header) (*http.Response, error) {
	ctx, cancel := context.WithCancel(ctx)
	var rd io.Reader
	if body != nil {
		rd = bytes.NewReader(body)
	}
	req, err := http.NewRequestWithContext(ctx, method, rawURL, rd)
	if err != nil {
		cancel()
		return nil, err
	}
	for _, hs := range []http.Header{x.headers, h} {
		for k, vs := range hs {
			req.Header[http.CanonicalHeaderKey(k)] = append([]string(nil), vs...)
		}
	}
	w := newWatchdog(x.idle, cancel)
	resp, err := x.client.Do(req)
	if err != nil {
		w.stop()
		cancel()
		if w.fired() {
			return nil, fmt.Errorf("%w: no response within %s", context.DeadlineExceeded, x.idle)
		}
		return nil, err
	}
	resp.Body = &watchedBody{rc: resp.Body, w: w, cancel: cancel}
	return resp, nil
}

type watchdog struct {
	mu    sync.Mutex
	t     *time.Timer
	d     time.Duration
	fire  bool
	close bool
}

func newWatchdog(d time.Duration, cancel context.CancelFunc) *watchdog {
	w := &watchdog{d: d}
	if d > 0 {
		w.t = time.AfterFunc(d, func() {
			w.mu.Lock()
			w.fire = !w.close
			w.mu.Unlock()
			if w.fire {
				cancel()
			}
		})
	}
	return w
}

func (w *watchdog) reset() {
	if w.t != nil {
		w.t.Reset(w.d)
	}
}

func (w *watchdog) stop() {
	w.mu.Lock()
	w.close = true
	w.mu.Unlock()
	if w.t != nil {
		w.t.Stop()
	}
}

func (w *watchdog) fired() bool {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.fire
}

type watchedBody struct {
	rc     io.ReadCloser
	w      *watchdog
	cancel context.CancelFunc
}

func (b *watchedBody) Read(p []byte) (int, error) {
	n, err := b.rc.Read(p)
	if n > 0 {
		b.w.reset()
	}
	if err != nil && b.w.fired() {
		return n, fmt.Errorf("%w: the response went silent for %s", context.DeadlineExceeded, b.w.d)
	}
	return n, err
}

func (b *watchedBody) Close() error {
	b.w.stop()
	err := b.rc.Close()
	b.cancel()
	return err
}

func mediaType(h http.Header) string {
	m, _, err := mime.ParseMediaType(h.Get("Content-Type"))
	if err != nil {
		return strings.ToLower(strings.TrimSpace(strings.SplitN(h.Get("Content-Type"), ";", 2)[0]))
	}
	return m
}

const maxJSONBody = 32 << 20

// streamable is the streamable HTTP transport (one POST per message).
type streamable struct {
	exchange
	url string

	mu      sync.Mutex
	session string
}

const (
	sessionHeader = "Mcp-Session-Id"
	// StartingHeader marks the gateway's 503 while another request starts the workload.
	StartingHeader = "X-AgentArea-MCP-Starting"
	// StartFailureHeader carries the gateway's classified startup failure.
	StartFailureHeader = "X-AgentArea-MCP-Start-Failure"
)

func (s *streamable) post(ctx context.Context, msg outbound, h http.Header) (*http.Response, error) {
	body, err := json.Marshal(msg)
	if err != nil {
		return nil, err
	}
	hh := http.Header{"Accept": {"application/json, text/event-stream"}, "Content-Type": {"application/json"}}
	s.mu.Lock()
	if s.session != "" {
		hh.Set(sessionHeader, s.session)
	}
	s.mu.Unlock()
	for k, vs := range h {
		hh[k] = vs
	}
	return s.do(ctx, http.MethodPost, s.url, body, hh)
}

// statusError is the transport's reading of a refused POST (the SDK's).
func (s *streamable) statusError(resp *http.Response) error {
	if resp.StatusCode == http.StatusUnauthorized || resp.StatusCode == http.StatusForbidden {
		return NewUnauthorizedError(s.url, resp.StatusCode, resp.Header.Get("WWW-Authenticate"))
	}
	if resp.StatusCode >= 300 && resp.StatusCode < 400 {
		return &RPCError{Code: CodeInvalidRequest, Message: fmt.Sprintf(
			"server redirected the request (HTTP %d) and redirects are not followed", resp.StatusCode)}
	}
	if mediaType(resp.Header) == "application/json" {
		raw, err := io.ReadAll(io.LimitReader(resp.Body, maxJSONBody))
		var m inbound
		if err == nil && json.Unmarshal(raw, &m) == nil && m.Error != nil {
			return m.Error
		}
	}
	if resp.StatusCode == http.StatusNotFound {
		s.mu.Lock()
		has := s.session != ""
		s.mu.Unlock()
		if has {
			return &RPCError{Code: CodeInvalidRequest, Message: "Session terminated"}
		}
		return &RPCError{Code: CodeMethodNotFound, Message: "Not Found"}
	}
	return &RPCError{Code: CodeInternalError, Message: "Server returned an error response"}
}

func (s *streamable) roundTrip(ctx context.Context, req outbound, h http.Header, notes func(inbound)) (inbound, error) {
	resp, err := s.post(ctx, req, h)
	if err != nil {
		return inbound{}, err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode == http.StatusAccepted {
		return inbound{}, &RPCError{Code: CodeInvalidRequest, Message: "server answered a request with 202 Accepted"}
	}
	if resp.StatusCode >= 300 {
		return inbound{}, s.statusError(resp)
	}
	if req.Method == "initialize" {
		if id := resp.Header.Get(sessionHeader); id != "" {
			s.mu.Lock()
			s.session = id
			s.mu.Unlock()
		}
	}
	switch ct := mediaType(resp.Header); ct {
	case "application/json":
		raw, err := io.ReadAll(io.LimitReader(resp.Body, maxJSONBody))
		if err != nil {
			return inbound{}, err
		}
		var m inbound
		if err := json.Unmarshal(raw, &m); err != nil {
			return inbound{}, &RPCError{Code: CodeParseError, Message: "Failed to parse JSON response: " + err.Error()}
		}
		return m, nil
	case "text/event-stream":
		rd := newSSEReader(resp.Body)
		for {
			ev, err := rd.next()
			if err != nil {
				if errors.Is(err, io.EOF) {
					err = io.ErrUnexpectedEOF
				}
				return inbound{}, fmt.Errorf("the response stream ended before the result: %w", err)
			}
			if ev.Name != "message" || strings.TrimSpace(ev.Data) == "" {
				continue
			}
			var m inbound
			if json.Unmarshal([]byte(ev.Data), &m) != nil {
				continue
			}
			if m.isResponse() && req.ID != nil && m.idIs(*req.ID) {
				return m, nil
			}
			if m.Method != "" && notes != nil {
				notes(m)
			}
		}
	default:
		return inbound{}, &RPCError{Code: CodeInvalidRequest, Message: "Unexpected content type: " + ct}
	}
}

func (s *streamable) send(ctx context.Context, msg outbound, h http.Header) error {
	resp, err := s.post(ctx, msg, h)
	if err != nil {
		return err
	}
	defer func() { _ = resp.Body.Close() }()
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode >= 300 {
		return s.statusError(resp)
	}
	return nil
}

func (s *streamable) close() {
	s.mu.Lock()
	id := s.session
	s.session = ""
	s.mu.Unlock()
	if id == "" {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	resp, err := s.do(ctx, http.MethodDelete, s.url, nil, http.Header{sessionHeader: {id}})
	if err == nil {
		_ = resp.Body.Close()
	}
}

// legacySSE is the HTTP+SSE transport of 2024-11-05: a GET stream carries
// every server message, POSTs to the endpoint it names carry the client's.
type legacySSE struct {
	exchange
	url      string
	endpoint string
	cancel   context.CancelFunc
	body     io.Closer

	mu      sync.Mutex
	waiting map[int64]chan inbound
	notes   map[int64]func(inbound)
	done    chan struct{}
	err     error
}

func openLegacySSE(ctx context.Context, x exchange, rawURL string) (*legacySSE, error) {
	streamCtx, cancel := context.WithCancel(context.Background())
	stop := context.AfterFunc(ctx, cancel)
	quiet := x
	quiet.idle = 0
	resp, err := quiet.do(streamCtx, http.MethodGet, rawURL, nil, http.Header{"Accept": {"text/event-stream"}})
	if err != nil {
		cancel()
		return nil, err
	}
	if resp.StatusCode == http.StatusUnauthorized || resp.StatusCode == http.StatusForbidden {
		_ = resp.Body.Close()
		cancel()
		return nil, NewUnauthorizedError(rawURL, resp.StatusCode, resp.Header.Get("WWW-Authenticate"))
	}
	if resp.StatusCode != http.StatusOK {
		_ = resp.Body.Close()
		cancel()
		return nil, &HTTPError{URL: rawURL, Status: resp.StatusCode}
	}
	s := &legacySSE{exchange: x, url: rawURL, cancel: cancel, body: resp.Body,
		waiting: map[int64]chan inbound{}, notes: map[int64]func(inbound){}, done: make(chan struct{})}
	rd := newSSEReader(resp.Body)
	ev, err := rd.next()
	for err == nil && ev.Name != "endpoint" {
		ev, err = rd.next()
	}
	if err != nil {
		s.close()
		return nil, fmt.Errorf("SSE stream ended before naming its endpoint: %w", err)
	}
	endpoint, err := sameOrigin(rawURL, strings.TrimSpace(ev.Data))
	if err != nil {
		s.close()
		return nil, err
	}
	stop()
	s.endpoint = endpoint
	go s.read(rd)
	return s, nil
}

func sameOrigin(base, ref string) (string, error) {
	b, err := url.Parse(base)
	if err != nil {
		return "", err
	}
	r, err := b.Parse(ref)
	if err != nil {
		return "", err
	}
	if r.Scheme != b.Scheme || r.Host != b.Host {
		return "", fmt.Errorf("endpoint origin does not match connection origin: %s", r.Redacted())
	}
	return r.String(), nil
}

func (s *legacySSE) read(rd *sseReader) {
	var err error
	for {
		var ev event
		ev, err = rd.next()
		if err != nil {
			break
		}
		if ev.Name != "message" {
			continue
		}
		var m inbound
		if json.Unmarshal([]byte(ev.Data), &m) != nil {
			continue
		}
		s.mu.Lock()
		if m.isResponse() {
			for id, ch := range s.waiting {
				if m.idIs(id) {
					ch <- m
					delete(s.waiting, id)
					break
				}
			}
		} else if m.Method != "" {
			for _, fn := range s.notes {
				fn(m)
			}
		}
		s.mu.Unlock()
	}
	if errors.Is(err, io.EOF) {
		err = io.ErrUnexpectedEOF
	}
	s.mu.Lock()
	s.err = fmt.Errorf("the SSE stream ended: %w", err)
	s.mu.Unlock()
	close(s.done)
}

func (s *legacySSE) postJSON(ctx context.Context, msg outbound, h http.Header) error {
	body, err := json.Marshal(msg)
	if err != nil {
		return err
	}
	hh := http.Header{"Content-Type": {"application/json"}}
	for k, vs := range h {
		hh[k] = vs
	}
	resp, err := s.do(ctx, http.MethodPost, s.endpoint, body, hh)
	if err != nil {
		return err
	}
	defer func() { _ = resp.Body.Close() }()
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode == http.StatusUnauthorized || resp.StatusCode == http.StatusForbidden {
		return NewUnauthorizedError(s.endpoint, resp.StatusCode, resp.Header.Get("WWW-Authenticate"))
	}
	if resp.StatusCode >= 300 {
		return &HTTPError{URL: s.endpoint, Status: resp.StatusCode}
	}
	return nil
}

func (s *legacySSE) roundTrip(ctx context.Context, req outbound, h http.Header, notes func(inbound)) (inbound, error) {
	ch := make(chan inbound, 1)
	id := *req.ID
	s.mu.Lock()
	s.waiting[id] = ch
	if notes != nil {
		s.notes[id] = notes
	}
	s.mu.Unlock()
	defer func() {
		s.mu.Lock()
		delete(s.waiting, id)
		delete(s.notes, id)
		s.mu.Unlock()
	}()
	if err := s.postJSON(ctx, req, h); err != nil {
		return inbound{}, err
	}
	select {
	case m := <-ch:
		return m, nil
	case <-s.done:
		s.mu.Lock()
		defer s.mu.Unlock()
		return inbound{}, s.err
	case <-ctx.Done():
		return inbound{}, ctx.Err()
	}
}

func (s *legacySSE) send(ctx context.Context, msg outbound, h http.Header) error {
	return s.postJSON(ctx, msg, h)
}

func (s *legacySSE) close() {
	s.cancel()
	if s.body != nil {
		_ = s.body.Close()
	}
}
