package connectortransport

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"io"
	"math/rand/v2"
	"net"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/agentarea/mcp-manager/internal/connectorproto"
	"github.com/agentarea/mcp-manager/internal/connectorproto/connectorprotoconnect"
	"golang.org/x/net/http2"
)

const (
	defaultReconnectInitial = 250 * time.Millisecond
	defaultReconnectMax     = 10 * time.Second
)

// ClientConfig is the outbound-only connector configuration. NodeCredential
// is placed solely in the transport Authorization header and is never copied
// into an envelope or returned in an error.
type ClientConfig struct {
	ControlPlaneURL     string
	DataPlaneID         string
	ConnectorInstanceID string
	NodeCredential      string
	ConnectorVersion    string
	Capabilities        []connectorproto.Capability
	MaxConcurrentOps    uint32
	HTTPClient          *http.Client
	TLSConfig           *tls.Config
	// AllowInsecureDevelopment permits clear-text HTTP only through a local
	// loopback tunnel. It exists for a developer running the control plane on
	// the same machine (or through ssh -R); arbitrary remote HTTP is refused.
	AllowInsecureDevelopment bool
	SendQueueSize            int
	ReconnectInitial         time.Duration
	ReconnectMax             time.Duration
	// OnSessionError receives sanitized transport failures before reconnect.
	// It must not block. The callback is optional and never receives credentials.
	OnSessionError func(error)
}

func (c ClientConfig) normalized() (ClientConfig, error) {
	if strings.TrimSpace(c.ControlPlaneURL) == "" || strings.TrimSpace(c.DataPlaneID) == "" || strings.TrimSpace(c.ConnectorInstanceID) == "" || strings.TrimSpace(c.NodeCredential) == "" || strings.TrimSpace(c.ConnectorVersion) == "" {
		return ClientConfig{}, errors.New("connector control plane URL, identity, credential, and version are required")
	}
	if strings.ContainsAny(c.NodeCredential, "\r\n") {
		return ClientConfig{}, errors.New("connector credential is invalid")
	}
	endpoint, err := url.Parse(c.ControlPlaneURL)
	if err != nil || endpoint.Host == "" || endpoint.User != nil || endpoint.RawQuery != "" || endpoint.Fragment != "" {
		return ClientConfig{}, errors.New("connector control plane URL must be an absolute URL without credentials, query, or fragment")
	}
	loopbackHTTP := endpoint.Scheme == "http" && c.AllowInsecureDevelopment && isLoopbackHostname(endpoint.Hostname())
	if endpoint.Scheme != "https" && !loopbackHTTP {
		return ClientConfig{}, errors.New("connector control plane URL must use HTTPS; development HTTP is limited to loopback")
	}
	if c.SendQueueSize <= 0 {
		c.SendQueueSize = 64
	}
	if c.ReconnectInitial <= 0 {
		c.ReconnectInitial = defaultReconnectInitial
	}
	if c.ReconnectMax <= 0 {
		c.ReconnectMax = defaultReconnectMax
	}
	if c.ReconnectInitial > c.ReconnectMax {
		return ClientConfig{}, errors.New("connector reconnect initial delay exceeds maximum")
	}
	if c.HTTPClient == nil {
		if loopbackHTTP {
			dialer := &net.Dialer{}
			c.HTTPClient = &http.Client{Transport: &http2.Transport{
				AllowHTTP: true,
				DialTLSContext: func(ctx context.Context, network, address string, _ *tls.Config) (net.Conn, error) {
					return dialer.DialContext(ctx, network, address)
				},
			}}
		} else {
			transport := http.DefaultTransport.(*http.Transport).Clone()
			transport.ForceAttemptHTTP2 = true
			transport.TLSClientConfig = c.TLSConfig
			c.HTTPClient = &http.Client{Transport: transport}
		}
	}
	return c, nil
}

func isLoopbackHostname(host string) bool {
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

// Dispatcher owns operation and proxy execution. The transport performs no
// provider setup and contains no workload-specific knowledge.
type Dispatcher interface {
	DispatchOperation(context.Context, *connectorproto.OperationStart) (*connectorproto.OperationResult, error)
	StartProxy(context.Context, *connectorproto.ProxyStart) (ProxyExchange, error)
}

// ProxyExchange accepts ordered control-plane request frames and publishes
// ordered connector response frames. Implementations must close Responses
// after emitting a terminal End frame (or after Close).
type ProxyExchange interface {
	WriteProxyRequest(context.Context, *connectorproto.ProxyRequestChunk) error
	EndProxyRequest(context.Context, *connectorproto.ProxyRequestEnd) error
	Responses() <-chan ProxyResponse
	Close() error
}

// ProxyResponse is one response frame from a connector-local proxy executor.
// Exactly one field should be set by an implementation.
type ProxyResponse struct {
	Headers *connectorproto.ProxyResponseHeaders
	Chunk   *connectorproto.ProxyResponseChunk
	End     *connectorproto.ProxyEnd
}

// Client owns no listener. Run maintains one outbound HTTP/2 Connect stream,
// reconnecting with bounded exponential backoff and jitter until ctx ends.
type Client struct {
	cfg        ClientConfig
	dispatcher Dispatcher
	service    connectorprotoconnect.OutboundConnectorClient
	mu         sync.Mutex
	session    *clientSession
}

func NewClient(cfg ClientConfig, dispatcher Dispatcher) (*Client, error) {
	if dispatcher == nil {
		return nil, errors.New("connector dispatcher is required")
	}
	normalized, err := cfg.normalized()
	if err != nil {
		return nil, err
	}
	return &Client{cfg: normalized, dispatcher: dispatcher, service: connectorprotoconnect.NewOutboundConnectorClient(normalized.HTTPClient, normalized.ControlPlaneURL)}, nil
}

func (c *Client) Run(ctx context.Context) error {
	delay := c.cfg.ReconnectInitial
	for {
		if err := ctx.Err(); err != nil {
			return nil
		}
		err := c.runSession(ctx)
		if ctx.Err() != nil {
			return nil
		}
		if err != nil && c.cfg.OnSessionError != nil {
			c.cfg.OnSessionError(err)
		}
		if err == nil {
			delay = c.cfg.ReconnectInitial
		} else {
			delay = minDuration(c.cfg.ReconnectMax, delay*2)
		}
		jitter := time.Duration(rand.Int64N(max(int64(delay/4), 1)))
		wait := delay - delay/8 + jitter
		select {
		case <-ctx.Done():
			return nil
		case <-time.After(wait):
		}
	}
}

// Drain announces shutdown to the control plane, then closes the active
// stream. It is safe to call before Run establishes a session.
func (c *Client) Drain(ctx context.Context) error {
	c.mu.Lock()
	session := c.session
	c.mu.Unlock()
	if session == nil {
		return nil
	}
	return session.drain(ctx)
}

func (c *Client) runSession(ctx context.Context) error {
	sessionCtx, cancel := context.WithCancel(ctx)
	defer cancel()
	stream := c.service.Connect(sessionCtx)
	stream.RequestHeader().Set("Authorization", "Bearer "+c.cfg.NodeCredential)
	streamDone := make(chan struct{})
	defer close(streamDone)
	defer stream.CloseRequest()
	defer stream.CloseResponse()
	// Context cancellation alone does not guarantee that a blocked ConnectRPC
	// Receive returns promptly on every HTTP/2 transport. Explicitly close both
	// halves so agent shutdown and reconnect cannot leave an active stream (and
	// its server-side logical session) behind.
	go func() {
		select {
		case <-sessionCtx.Done():
			_ = stream.CloseRequest()
			_ = stream.CloseResponse()
		case <-streamDone:
		}
	}()
	outgoing := make(chan outboundMessage, c.cfg.SendQueueSize)
	writerErr := make(chan error, 1)
	go func() {
		for {
			select {
			case <-sessionCtx.Done():
				writerErr <- sessionCtx.Err()
				return
			case outbound := <-outgoing:
				if err := stream.Send(outbound.message); err != nil {
					outbound.complete(err)
					writerErr <- err
					return
				}
				outbound.complete(nil)
			}
		}
	}()
	incoming := make(chan inboundMessage, 1)
	go func() {
		for {
			message, err := stream.Receive()
			select {
			case incoming <- inboundMessage{message: message, err: err}:
			case <-sessionCtx.Done():
				return
			}
			if err != nil {
				return
			}
		}
	}()
	state := newClientSession(c, sessionCtx, outgoing)
	c.mu.Lock()
	c.session = state
	c.mu.Unlock()
	defer func() {
		c.mu.Lock()
		if c.session == state {
			c.session = nil
		}
		c.mu.Unlock()
	}()
	defer state.close()
	if err := state.send(ctx, &connectorproto.ConnectorToControl_Hello{Hello: &connectorproto.Hello{
		ConnectorVersion:        c.cfg.ConnectorVersion,
		Capabilities:            append([]connectorproto.Capability(nil), c.cfg.Capabilities...),
		MaxConcurrentOperations: c.cfg.MaxConcurrentOps,
	}}); err != nil {
		return err
	}
	for {
		var received inboundMessage
		select {
		case err := <-writerErr:
			return err
		case <-sessionCtx.Done():
			return sessionCtx.Err()
		case <-state.ctx.Done():
			// The session has its own cancellation boundary so heartbeat and drain
			// failures can invalidate all in-flight provider work. Do not leave the
			// transport attached to that cancelled child: returning closes both
			// stream halves and lets Run establish a fresh logical session.
			return context.Cause(state.ctx)
		case received = <-incoming:
		}
		if received.err != nil {
			if errors.Is(received.err, io.EOF) {
				return nil
			}
			return received.err
		}
		message := received.message
		if message == nil {
			return errors.New("control plane returned an empty connector message")
		}
		if err := connectorproto.ValidateControlToConnector(message); err != nil {
			return errors.New("control plane sent invalid connector message")
		}
		if message.GetDataPlaneId().GetValue() != c.cfg.DataPlaneID || message.GetConnectorInstanceId().GetValue() != c.cfg.ConnectorInstanceID {
			return errors.New("control plane connector identity mismatch")
		}
		if err := state.handle(message); err != nil {
			return err
		}
	}
}

type clientSession struct {
	client     *Client
	ctx        context.Context
	cancel     context.CancelCauseFunc
	outgoing   chan<- outboundMessage
	mu         sync.Mutex
	accepted   bool
	draining   bool
	operations map[string]context.CancelFunc
	proxies    map[string]ProxyExchange
}

type outboundMessage struct {
	message *connectorproto.ConnectorToControl
	done    chan error
}

type inboundMessage struct {
	message *connectorproto.ControlToConnector
	err     error
}

func (o outboundMessage) complete(err error) {
	if o.done != nil {
		o.done <- err
	}
}

func newClientSession(client *Client, ctx context.Context, outgoing chan<- outboundMessage) *clientSession {
	child, cancel := context.WithCancelCause(ctx)
	return &clientSession{client: client, ctx: child, cancel: cancel, outgoing: outgoing, operations: make(map[string]context.CancelFunc), proxies: make(map[string]ProxyExchange)}
}

func (s *clientSession) close() {
	s.cancel(context.Canceled)
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, cancel := range s.operations {
		cancel()
	}
	for _, proxy := range s.proxies {
		_ = proxy.Close()
	}
}

func (s *clientSession) send(ctx context.Context, payload any) error {
	return s.enqueue(ctx, payload, false)
}

func (s *clientSession) sendSync(ctx context.Context, payload any) error {
	return s.enqueue(ctx, payload, true)
}

func (s *clientSession) enqueue(ctx context.Context, payload any, wait bool) error {
	message := &connectorproto.ConnectorToControl{ProtocolVersion: connectorproto.ProtocolVersionV1, DataPlaneId: &connectorproto.DataPlaneID{Value: s.client.cfg.DataPlaneID}, ConnectorInstanceId: &connectorproto.ConnectorInstanceID{Value: s.client.cfg.ConnectorInstanceID}}
	switch payload := payload.(type) {
	case *connectorproto.ConnectorToControl_Hello:
		message.Message = payload
	case *connectorproto.ConnectorToControl_CapabilityReport:
		message.Message = payload
	case *connectorproto.ConnectorToControl_Heartbeat:
		message.Message = payload
	case *connectorproto.ConnectorToControl_Drain:
		message.Message = payload
	case *connectorproto.ConnectorToControl_Error:
		message.Message = payload
	case *connectorproto.ConnectorToControl_OperationAck:
		message.Message = payload
	case *connectorproto.ConnectorToControl_OperationResult:
		message.Message = payload
	case *connectorproto.ConnectorToControl_ProxyResponseHeaders:
		message.Message = payload
	case *connectorproto.ConnectorToControl_ProxyResponseChunk:
		message.Message = payload
	case *connectorproto.ConnectorToControl_ProxyEnd:
		message.Message = payload
	default:
		return errors.New("unsupported connector message")
	}
	if err := connectorproto.ValidateConnectorToControl(message); err != nil {
		return err
	}
	outbound := outboundMessage{message: message}
	if wait {
		outbound.done = make(chan error, 1)
	}
	select {
	case <-s.ctx.Done():
		return s.ctx.Err()
	case <-ctx.Done():
		return ctx.Err()
	case s.outgoing <- outbound:
	default:
		return errors.New("connector send queue is full")
	}
	if !wait {
		return nil
	}
	select {
	case err := <-outbound.done:
		return err
	case <-s.ctx.Done():
		return s.ctx.Err()
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (s *clientSession) handle(message *connectorproto.ControlToConnector) error {
	if !s.accepted {
		if message.GetHelloAccepted() == nil {
			return errors.New("control plane did not accept connector hello")
		}
		s.accepted = true
		s.startHeartbeats(time.Duration(message.GetHelloAccepted().GetHeartbeatIntervalMillis()) * time.Millisecond)
		return s.send(s.ctx, &connectorproto.ConnectorToControl_CapabilityReport{CapabilityReport: &connectorproto.CapabilityReport{Capabilities: append([]connectorproto.Capability(nil), s.client.cfg.Capabilities...), MaxConcurrentOperations: s.client.cfg.MaxConcurrentOps}})
	}
	switch body := message.GetMessage().(type) {
	case *connectorproto.ControlToConnector_Heartbeat, *connectorproto.ControlToConnector_Error:
		return nil
	case *connectorproto.ControlToConnector_Drain:
		s.mu.Lock()
		s.draining = true
		s.mu.Unlock()
		return nil
	case *connectorproto.ControlToConnector_OperationStart:
		s.startOperation(body.OperationStart)
		return nil
	case *connectorproto.ControlToConnector_OperationCancel:
		s.mu.Lock()
		cancel := s.operations[body.OperationCancel.GetOperationId().GetValue()]
		s.mu.Unlock()
		if cancel != nil {
			cancel()
		}
		return nil
	case *connectorproto.ControlToConnector_ProxyStart:
		return s.startProxy(body.ProxyStart)
	case *connectorproto.ControlToConnector_ProxyRequestChunk:
		return s.writeProxy(body.ProxyRequestChunk)
	case *connectorproto.ControlToConnector_ProxyRequestEnd:
		return s.endProxy(body.ProxyRequestEnd)
	default:
		return errors.New("unsupported control plane message")
	}
}

func (s *clientSession) startOperation(start *connectorproto.OperationStart) {
	id := start.GetOperationId().GetValue()
	s.mu.Lock()
	draining := s.draining
	s.mu.Unlock()
	if draining {
		_ = s.send(s.ctx, &connectorproto.ConnectorToControl_OperationAck{OperationAck: &connectorproto.OperationAck{OperationId: start.GetOperationId(), Accepted: false, Rejection: &connectorproto.Error{Code: connectorproto.ErrorCode_ERROR_CODE_UNAVAILABLE, Message: "connector draining"}}})
		return
	}
	ctx, cancel := deadlineContext(s.ctx, start.GetDeadlineUnixMillis())
	s.mu.Lock()
	if existing := s.operations[id]; existing != nil {
		s.mu.Unlock()
		_ = s.send(s.ctx, &connectorproto.ConnectorToControl_OperationAck{OperationAck: &connectorproto.OperationAck{OperationId: start.GetOperationId(), Accepted: false, Rejection: &connectorproto.Error{Code: connectorproto.ErrorCode_ERROR_CODE_INVALID_ARGUMENT, Message: "duplicate operation"}}})
		cancel()
		return
	}
	s.operations[id] = cancel
	s.mu.Unlock()
	if err := s.send(s.ctx, &connectorproto.ConnectorToControl_OperationAck{OperationAck: &connectorproto.OperationAck{OperationId: start.GetOperationId(), Accepted: true}}); err != nil {
		cancel()
		return
	}
	go func() {
		defer func() { s.mu.Lock(); delete(s.operations, id); s.mu.Unlock(); cancel() }()
		result, err := s.client.dispatcher.DispatchOperation(ctx, start)
		if result == nil {
			result = &connectorproto.OperationResult{OperationId: start.GetOperationId(), Status: connectorproto.OperationResultStatus_OPERATION_RESULT_STATUS_FAILED}
		}
		result.OperationId = start.GetOperationId()
		if err != nil && ctx.Err() != nil {
			if errors.Is(ctx.Err(), context.DeadlineExceeded) {
				result.Status = connectorproto.OperationResultStatus_OPERATION_RESULT_STATUS_DEADLINE_EXCEEDED
				result.Error = &connectorproto.Error{Code: connectorproto.ErrorCode_ERROR_CODE_DEADLINE_EXCEEDED, Message: "connector operation deadline exceeded"}
			} else {
				result.Status = connectorproto.OperationResultStatus_OPERATION_RESULT_STATUS_CANCELLED
				result.Error = &connectorproto.Error{Code: connectorproto.ErrorCode_ERROR_CODE_CANCELLED, Message: "connector operation cancelled"}
			}
		} else if err != nil {
			result.Status = connectorproto.OperationResultStatus_OPERATION_RESULT_STATUS_FAILED
			result.Error = &connectorproto.Error{Code: connectorproto.ErrorCode_ERROR_CODE_INTERNAL, Message: "connector operation failed"}
		} else if ctx.Err() != nil {
			result.Status = connectorproto.OperationResultStatus_OPERATION_RESULT_STATUS_CANCELLED
			result.Error = &connectorproto.Error{Code: connectorproto.ErrorCode_ERROR_CODE_CANCELLED, Message: "connector operation cancelled"}
		}
		_ = s.send(s.ctx, &connectorproto.ConnectorToControl_OperationResult{OperationResult: result})
	}()
}

func (s *clientSession) startProxy(start *connectorproto.ProxyStart) error {
	id := start.GetRequestId().GetValue()
	s.mu.Lock()
	draining := s.draining
	s.mu.Unlock()
	if draining {
		return s.send(s.ctx, &connectorproto.ConnectorToControl_ProxyEnd{ProxyEnd: &connectorproto.ProxyEnd{RequestId: start.GetRequestId(), Reason: connectorproto.ProxyEndReason_PROXY_END_REASON_ERROR, Error: &connectorproto.Error{Code: connectorproto.ErrorCode_ERROR_CODE_UNAVAILABLE, Message: "connector draining"}}})
	}
	ctx, cancel := deadlineContext(s.ctx, start.GetDeadlineUnixMillis())
	proxy, err := s.client.dispatcher.StartProxy(ctx, start)
	if err != nil {
		cancel()
		return s.send(s.ctx, &connectorproto.ConnectorToControl_ProxyEnd{ProxyEnd: &connectorproto.ProxyEnd{RequestId: start.GetRequestId(), Reason: connectorproto.ProxyEndReason_PROXY_END_REASON_ERROR, Error: &connectorproto.Error{Code: connectorproto.ErrorCode_ERROR_CODE_INTERNAL, Message: "connector proxy unavailable"}}})
	}
	s.mu.Lock()
	if _, exists := s.proxies[id]; exists {
		s.mu.Unlock()
		cancel()
		_ = proxy.Close()
		return errors.New("duplicate proxy request")
	}
	s.proxies[id] = proxy
	s.mu.Unlock()
	go func() {
		defer func() {
			cancel()
			_ = proxy.Close()
			s.mu.Lock()
			delete(s.proxies, id)
			s.mu.Unlock()
		}()
		for response := range proxy.Responses() {
			var payload any
			switch {
			case response.Headers != nil:
				response.Headers.RequestId = start.GetRequestId()
				payload = &connectorproto.ConnectorToControl_ProxyResponseHeaders{ProxyResponseHeaders: response.Headers}
			case response.Chunk != nil:
				response.Chunk.RequestId = start.GetRequestId()
				payload = &connectorproto.ConnectorToControl_ProxyResponseChunk{ProxyResponseChunk: response.Chunk}
			case response.End != nil:
				response.End.RequestId = start.GetRequestId()
				payload = &connectorproto.ConnectorToControl_ProxyEnd{ProxyEnd: response.End}
			default:
				continue
			}
			if s.send(s.ctx, payload) != nil {
				return
			}
		}
	}()
	return nil
}

func (s *clientSession) writeProxy(chunk *connectorproto.ProxyRequestChunk) error {
	id := chunk.GetRequestId().GetValue()
	s.mu.Lock()
	proxy := s.proxies[id]
	s.mu.Unlock()
	if proxy == nil {
		return errors.New("unknown proxy request")
	}
	if err := proxy.WriteProxyRequest(s.ctx, chunk); err != nil {
		return s.send(s.ctx, &connectorproto.ConnectorToControl_ProxyEnd{ProxyEnd: &connectorproto.ProxyEnd{RequestId: chunk.GetRequestId(), Reason: connectorproto.ProxyEndReason_PROXY_END_REASON_ERROR, Error: &connectorproto.Error{Code: connectorproto.ErrorCode_ERROR_CODE_INTERNAL, Message: "connector proxy write failed"}}})
	}
	return nil
}

func (s *clientSession) endProxy(end *connectorproto.ProxyRequestEnd) error {
	id := end.GetRequestId().GetValue()
	s.mu.Lock()
	proxy := s.proxies[id]
	s.mu.Unlock()
	if proxy == nil {
		// Terminal frames are idempotent. The local response goroutine may have
		// already removed a completed exchange before a delayed control-plane
		// close arrives; treating that harmless race as a protocol failure would
		// disconnect every other operation on this data plane.
		return nil
	}
	if err := proxy.EndProxyRequest(s.ctx, end); err != nil {
		return s.send(s.ctx, &connectorproto.ConnectorToControl_ProxyEnd{ProxyEnd: &connectorproto.ProxyEnd{RequestId: end.GetRequestId(), Reason: connectorproto.ProxyEndReason_PROXY_END_REASON_ERROR, Error: &connectorproto.Error{Code: connectorproto.ErrorCode_ERROR_CODE_INTERNAL, Message: "connector proxy close failed"}}})
	}
	return nil
}

func deadlineContext(parent context.Context, deadlineMillis int64) (context.Context, context.CancelFunc) {
	if deadlineMillis <= 0 {
		return context.WithCancel(parent)
	}
	return context.WithDeadline(parent, time.UnixMilli(deadlineMillis))
}

func minDuration(a, b time.Duration) time.Duration {
	if a < b {
		return a
	}
	return b
}

func (s *clientSession) startHeartbeats(interval time.Duration) {
	if interval <= 0 {
		interval = defaultHeartbeatInterval
	}
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for {
			select {
			case <-s.ctx.Done():
				return
			case at := <-ticker.C:
				// A heartbeat proves a live write, not merely admission to the local
				// queue. A failed write invalidates the child session; runSession
				// observes that cancellation and reconnects immediately.
				if err := s.sendSync(s.ctx, &connectorproto.ConnectorToControl_Heartbeat{Heartbeat: &connectorproto.Heartbeat{SentAtUnixMillis: at.UnixMilli()}}); err != nil {
					s.cancel(fmt.Errorf("send connector heartbeat: %w", err))
					return
				}
			}
		}
	}()
}

func (s *clientSession) drain(ctx context.Context) error {
	s.mu.Lock()
	if s.draining {
		s.mu.Unlock()
		return nil
	}
	s.draining = true
	s.mu.Unlock()
	deadline := time.Now().Add(10 * time.Second)
	if value, ok := ctx.Deadline(); ok {
		deadline = value
	}
	err := s.sendSync(ctx, &connectorproto.ConnectorToControl_Drain{Drain: &connectorproto.Drain{Reason: connectorproto.DrainReason_DRAIN_REASON_SHUTDOWN, DeadlineUnixMillis: deadline.UnixMilli()}})
	s.cancel(context.Canceled)
	return err
}
