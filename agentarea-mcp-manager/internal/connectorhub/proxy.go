package connectorhub

import (
	"context"
	"errors"
	"fmt"
	"io"
	"sync"
	"time"
)

// ProxyRequest is an origin-form request to be sent through a connector. The
// hub does not retain its headers after the start command has been handed to
// the transport.
type ProxyRequest struct {
	ID       string
	Method   string
	Path     string
	Headers  []Header
	Deadline time.Time
}

type ProxyResponseHeaders struct {
	StatusCode int
	Headers    []Header
}

// ProxyCall is a bidirectional proxy exchange. Calls are tied to a connector
// session generation: receiving data from an old session is rejected before it
// can reach a newly opened exchange.
type ProxyCall struct {
	hub     *Hub
	session *Session
	id      string

	mu              sync.Mutex
	requestMu       sync.Mutex
	requestClosed   bool
	responseHeader  *ProxyResponseHeaders
	chunks          [][]byte
	terminal        bool
	err             error
	changed         chan struct{}
	done            chan struct{}
	nextRequestSeq  uint64
	nextResponseSeq uint64
}

func (p *ProxyCall) ID() string { return p.id }

func (h *Hub) OpenProxy(ctx context.Context, dataPlaneID string, request ProxyRequest) (*ProxyCall, error) {
	if request.Method == "" || request.Path == "" {
		return nil, fmt.Errorf("proxy method and path are required")
	}
	if request.ID == "" {
		var err error
		request.ID, err = newID()
		if err != nil {
			return nil, err
		}
	}
	h.mu.Lock()
	session, err := h.usableSessionLocked(dataPlaneID, CapabilityProxy)
	if err == nil {
		if _, used := session.usedProxyIDs[request.ID]; used {
			err = ErrProxyExists
		}
	}
	if err != nil {
		h.mu.Unlock()
		return nil, err
	}
	session.usedProxyIDs[request.ID] = struct{}{}
	call := &ProxyCall{hub: h, session: session, id: request.ID, changed: make(chan struct{}), done: make(chan struct{})}
	h.proxies[proxyKey(dataPlaneID, request.ID)] = call
	h.mu.Unlock()
	// Copying headers makes the sender's transient command independent of a
	// caller that reuses its slice. The call itself retains no header values.
	headers := append([]Header(nil), request.Headers...)
	command := Command{Kind: CommandProxyStart, DataPlaneID: dataPlaneID, InstanceID: session.instanceID, Generation: session.generation, Proxy: &ProxyStart{ID: request.ID, Method: request.Method, Path: request.Path, Headers: headers, DeadlineUnixMilli: effectiveDeadline(ctx, request.Deadline)}}
	if err := session.send(ctx, command); err != nil {
		h.removeProxy(call)
		call.fail(err)
		if err != context.Canceled && err != context.DeadlineExceeded {
			h.disconnect(session)
		}
		return nil, err
	}
	if ctx.Done() != nil {
		go call.closeWhenContextEnds(ctx)
	}
	return call, nil
}

func (p *ProxyCall) closeWhenContextEnds(ctx context.Context) {
	select {
	case <-ctx.Done():
		p.Close()
	case <-p.done:
	}
}

// Write sends one ordered request chunk. Sending after CloseRequest or Close
// is rejected locally and does not touch the transport.
func (p *ProxyCall) Write(ctx context.Context, data []byte) error {
	p.requestMu.Lock()
	defer p.requestMu.Unlock()
	p.mu.Lock()
	if p.requestClosed || p.terminal {
		p.mu.Unlock()
		return ErrProxyClosed
	}
	sequence := p.nextRequestSeq
	p.nextRequestSeq++
	p.mu.Unlock()
	chunk := append([]byte(nil), data...)
	err := p.session.send(ctx, Command{Kind: CommandProxyChunk, DataPlaneID: p.session.dataPlaneID, InstanceID: p.session.instanceID, Generation: p.session.generation, Chunk: &ProxyChunk{ID: p.id, Sequence: sequence, Data: chunk}})
	if err != nil {
		p.fail(err)
		p.hub.removeProxy(p)
		if err != context.Canceled && err != context.DeadlineExceeded {
			p.hub.disconnect(p.session)
		}
	}
	return err
}

func (p *ProxyCall) CloseRequest(ctx context.Context) error {
	p.requestMu.Lock()
	defer p.requestMu.Unlock()
	p.mu.Lock()
	if p.requestClosed {
		p.mu.Unlock()
		return nil
	}
	if p.terminal {
		p.mu.Unlock()
		return ErrProxyClosed
	}
	p.requestClosed = true
	p.mu.Unlock()
	err := p.session.send(ctx, Command{Kind: CommandProxyEnd, DataPlaneID: p.session.dataPlaneID, InstanceID: p.session.instanceID, Generation: p.session.generation, ProxyEnd: &ProxyEnd{ID: p.id, Reason: "complete"}})
	if err != nil {
		p.fail(err)
		p.hub.removeProxy(p)
		if err != context.Canceled && err != context.DeadlineExceeded {
			p.hub.disconnect(p.session)
		}
	}
	return err
}

// Close cancels the proxy locally and informs a live connector. Unlike
// lifecycle operations a proxy is never retained for reconnect/replay.
func (p *ProxyCall) Close() {
	p.requestMu.Lock()
	defer p.requestMu.Unlock()
	transitioned := p.fail(ErrProxyClosed)
	p.hub.removeProxy(p)
	// http.Response.Body.Close is called after a normal EOF too. Once the
	// connector has already sent its terminal frame, sending a second cancel can
	// race exchange cleanup and must not tear down the whole connector session.
	if !transitioned {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	_ = p.session.send(ctx, Command{Kind: CommandProxyEnd, DataPlaneID: p.session.dataPlaneID, InstanceID: p.session.instanceID, Generation: p.session.generation, ProxyEnd: &ProxyEnd{ID: p.id, Reason: "cancelled"}})
}

func (p *ProxyCall) Headers(ctx context.Context) (*ProxyResponseHeaders, error) {
	for {
		p.mu.Lock()
		if p.responseHeader != nil {
			headers := cloneHeaders(p.responseHeader)
			p.mu.Unlock()
			return headers, nil
		}
		if p.terminal {
			err := p.err
			if err == nil {
				err = io.EOF
			}
			p.mu.Unlock()
			return nil, err
		}
		changed := p.changed
		p.mu.Unlock()
		select {
		case <-changed:
		case <-ctx.Done():
			p.Close()
			return nil, ctx.Err()
		}
	}
}

// Read returns response chunks in wire order. A context cancellation closes
// this proxy exchange, preventing unread buffered data from surviving a
// caller that has gone away.
func (p *ProxyCall) Read(ctx context.Context) ([]byte, error) {
	for {
		p.mu.Lock()
		if len(p.chunks) > 0 {
			chunk := p.chunks[0]
			p.chunks[0] = nil
			p.chunks = p.chunks[1:]
			p.mu.Unlock()
			return chunk, nil
		}
		if p.terminal {
			err := p.err
			if err == nil {
				err = io.EOF
			}
			p.mu.Unlock()
			return nil, err
		}
		changed := p.changed
		p.mu.Unlock()
		select {
		case <-changed:
		case <-ctx.Done():
			p.Close()
			return nil, ctx.Err()
		}
	}
}

func (p *ProxyCall) fail(err error) bool {
	p.mu.Lock()
	transitioned := false
	if !p.terminal {
		p.terminal, p.err = true, err
		close(p.changed)
		close(p.done)
		transitioned = true
	}
	p.mu.Unlock()
	return transitioned
}

func (h *Hub) removeProxy(call *ProxyCall) {
	h.mu.Lock()
	key := proxyKey(call.session.dataPlaneID, call.id)
	if h.proxies[key] == call {
		delete(h.proxies, key)
	}
	h.mu.Unlock()
}

func (s *Session) ProxyHeaders(id string, headers ProxyResponseHeaders) error {
	call, err := s.currentProxy(id)
	if err != nil {
		return err
	}
	call.mu.Lock()
	defer call.mu.Unlock()
	if call.terminal || call.responseHeader != nil {
		return ErrInvalidLifecycle
	}
	call.responseHeader = cloneHeaders(&headers)
	close(call.changed)
	call.changed = make(chan struct{})
	return nil
}

func (s *Session) ProxyChunk(id string, sequence uint64, data []byte) error {
	call, err := s.currentProxy(id)
	if err != nil {
		return err
	}
	call.mu.Lock()
	if call.terminal {
		call.mu.Unlock()
		return ErrInvalidLifecycle
	}
	if sequence != call.nextResponseSeq {
		call.mu.Unlock()
		return ErrInvalidLifecycle
	}
	if len(call.chunks) >= call.hub.config.PerStreamBuffer {
		call.terminal, call.err = true, ErrStreamBackpressure
		close(call.changed)
		close(call.done)
		call.mu.Unlock()
		call.hub.removeProxy(call)
		go call.sendBackpressureEnd()
		return ErrStreamBackpressure
	}
	call.nextResponseSeq++
	call.chunks = append(call.chunks, append([]byte(nil), data...))
	close(call.changed)
	call.changed = make(chan struct{})
	call.mu.Unlock()
	return nil
}

func (p *ProxyCall) sendBackpressureEnd() {
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	_ = p.session.send(ctx, Command{Kind: CommandProxyEnd, DataPlaneID: p.session.dataPlaneID, InstanceID: p.session.instanceID, Generation: p.session.generation, ProxyEnd: &ProxyEnd{ID: p.id, Reason: "backpressure"}})
}

func (s *Session) ProxyEnd(id, reason string) error {
	call, err := s.currentProxy(id)
	if err != nil {
		// A normal HTTP response can make its body reader remove the proxy at the
		// same time the connector's terminal frame arrives. Terminal delivery is
		// idempotent for an ID already admitted by this live session; accepting the
		// duplicate avoids tearing down every other operation on the data plane.
		h := s.hub
		h.mu.Lock()
		_, used := s.usedProxyIDs[id]
		current := h.isCurrentLocked(s)
		h.mu.Unlock()
		if current && used {
			return nil
		}
		return err
	}
	call.mu.Lock()
	if !call.terminal {
		call.terminal = true
		if reason != "complete" {
			call.err = errors.New(reason)
		}
		close(call.changed)
		close(call.done)
	}
	call.mu.Unlock()
	s.hub.removeProxy(call)
	return nil
}

func (s *Session) currentProxy(id string) (*ProxyCall, error) {
	h := s.hub
	h.mu.Lock()
	defer h.mu.Unlock()
	if !h.isCurrentLocked(s) {
		return nil, ErrStaleSession
	}
	call := h.proxies[proxyKey(s.dataPlaneID, id)]
	if call == nil || call.session != s {
		return nil, ErrStaleSession
	}
	return call, nil
}

func proxyKey(dataPlaneID, id string) string { return dataPlaneID + "\x00" + id }

func cloneHeaders(headers *ProxyResponseHeaders) *ProxyResponseHeaders {
	if headers == nil {
		return nil
	}
	copy := *headers
	copy.Headers = append([]Header(nil), headers.Headers...)
	return &copy
}
