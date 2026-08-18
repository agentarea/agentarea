// Package connectorhub owns the in-memory control-plane view of outbound
// data-plane connectors. It deliberately has no dependency on a particular
// streaming RPC implementation; an adapter only has to implement Sender.
package connectorhub

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"sync"
	"time"
)

var (
	ErrConnectorActive        = errors.New("connector already active for data plane")
	ErrConnectorUnavailable   = errors.New("connector unavailable")
	ErrConnectorDraining      = errors.New("connector is draining")
	ErrCapabilityUnavailable  = errors.New("connector capability unavailable")
	ErrInFlightLimit          = errors.New("connector in-flight operation limit reached")
	ErrOperationExists        = errors.New("operation ID has already been used")
	ErrProxyExists            = errors.New("proxy stream ID has already been used")
	ErrStaleSession           = errors.New("message belongs to a stale connector session")
	ErrInvalidLifecycle       = errors.New("invalid operation lifecycle transition")
	ErrOperationIndeterminate = errors.New("operation acknowledged but connector disconnected")
	ErrProxyDisconnected      = errors.New("connector disconnected during proxy exchange")
	ErrStreamBackpressure     = errors.New("proxy response buffer is full")
	ErrProxyClosed            = errors.New("proxy stream is closed")
)

// Capability is intentionally a string. The wire protocol can map its enum
// values here without making this package transport dependent.
type Capability string

const (
	CapabilityOperations Capability = "operations"
	CapabilityProxy      Capability = "proxy"
)

// Config controls only control-plane memory and concurrency bounds.
type Config struct {
	MaxInFlightOperations int
	PerStreamBuffer       int
}

func (c Config) normalized() Config {
	if c.MaxInFlightOperations <= 0 {
		c.MaxInFlightOperations = 32
	}
	if c.PerStreamBuffer <= 0 {
		c.PerStreamBuffer = 32
	}
	return c
}

// Sender is the only transport-facing dependency. Implementations should
// return when ctx ends. The hub serializes calls for a session.
type Sender interface {
	Send(context.Context, Command) error
}

type CommandKind string

const (
	CommandOperationStart  CommandKind = "operation_start"
	CommandOperationCancel CommandKind = "operation_cancel"
	CommandProxyStart      CommandKind = "proxy_start"
	CommandProxyChunk      CommandKind = "proxy_request_chunk"
	CommandProxyEnd        CommandKind = "proxy_end"
)

// Command contains no authentication fields. It is transient: the hub does
// not retain it after Send returns.
type Command struct {
	Kind        CommandKind
	DataPlaneID string
	InstanceID  string
	Generation  uint64
	Operation   *OperationStart
	Cancel      *OperationCancel
	Proxy       *ProxyStart
	Chunk       *ProxyChunk
	ProxyEnd    *ProxyEnd
}

type OperationStart struct {
	ID                string
	Kind              string
	DeadlineUnixMilli int64
	Payload           []byte
	ContentType       string
}

type OperationCancel struct {
	ID     string
	Reason string
}

// Header is a proxy protocol value. Headers are passed to Sender but never
// retained by the hub.
type Header struct{ Name, Value string }

type ProxyStart struct {
	ID                string
	Method            string
	Path              string
	Headers           []Header
	DeadlineUnixMilli int64
}

type ProxyChunk struct {
	ID       string
	Sequence uint64
	Data     []byte
}

type ProxyEnd struct {
	ID     string
	Reason string
}

type Registration struct {
	DataPlaneID         string
	ConnectorInstanceID string
	Capabilities        []Capability
	MaxConcurrentOps    int
	Sender              Sender
}

// Hub is safe for concurrent registration, calls, transport sends and inbound
// messages. It stores neither connector credentials nor a logger.
type Hub struct {
	mu          sync.Mutex
	config      Config
	sessions    map[string]*Session
	generations map[string]uint64
	operations  map[string]*operation
	proxies     map[string]*ProxyCall
}

func New(config Config) *Hub {
	return &Hub{
		config:      config.normalized(),
		sessions:    make(map[string]*Session),
		generations: make(map[string]uint64),
		operations:  make(map[string]*operation),
		proxies:     make(map[string]*ProxyCall),
	}
}

// NewHub is the explicit constructor name for wiring layers.
func NewHub(config Config) *Hub { return New(config) }

// Register admits exactly one live session for a logical data plane. A caller
// must Close the old session before a connector can take over.
func (h *Hub) Register(reg Registration) (*Session, error) {
	if reg.DataPlaneID == "" || reg.ConnectorInstanceID == "" || reg.Sender == nil {
		return nil, fmt.Errorf("data plane ID, connector instance ID, and sender are required")
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	if current := h.sessions[reg.DataPlaneID]; current != nil && !current.closed {
		return nil, ErrConnectorActive
	}
	capabilities := make(map[Capability]struct{}, len(reg.Capabilities))
	for _, capability := range reg.Capabilities {
		capabilities[capability] = struct{}{}
	}
	limit := h.config.MaxInFlightOperations
	if reg.MaxConcurrentOps > 0 && reg.MaxConcurrentOps < limit {
		limit = reg.MaxConcurrentOps
	}
	generation := h.generations[reg.DataPlaneID] + 1
	session := &Session{
		hub: h, dataPlaneID: reg.DataPlaneID, instanceID: reg.ConnectorInstanceID,
		generation: generation, sender: reg.Sender, capabilities: capabilities, operationLimit: limit,
		usedProxyIDs: make(map[string]struct{}),
	}
	h.generations[reg.DataPlaneID] = generation
	h.sessions[reg.DataPlaneID] = session
	return session, nil
}

// Session is an opaque capability for an active connector transport. Inbound
// messages must be submitted through the Session that received them, which
// makes generation fencing automatic.
type Session struct {
	hub            *Hub
	dataPlaneID    string
	instanceID     string
	generation     uint64
	sender         Sender
	sendMu         sync.Mutex
	capabilities   map[Capability]struct{}
	operationLimit int
	inFlight       int
	draining       bool
	closed         bool
	usedProxyIDs   map[string]struct{}
}

func (s *Session) DataPlaneID() string         { return s.dataPlaneID }
func (s *Session) ConnectorInstanceID() string { return s.instanceID }
func (s *Session) Generation() uint64          { return s.generation }

// SetDraining gates new operations and proxy calls. Existing work continues.
func (s *Session) SetDraining(draining bool) error {
	h := s.hub
	h.mu.Lock()
	defer h.mu.Unlock()
	if !h.isCurrentLocked(s) {
		return ErrStaleSession
	}
	s.draining = draining
	return nil
}

// SetCapabilities replaces the capabilities reported by a live connector.
// The transport calls this after the initial HelloAccepted exchange and on
// later capability reports. Existing calls remain valid; the change only
// gates newly admitted work.
func (s *Session) SetCapabilities(capabilities []Capability, maxConcurrentOps int) error {
	h := s.hub
	h.mu.Lock()
	defer h.mu.Unlock()
	if !h.isCurrentLocked(s) {
		return ErrStaleSession
	}
	updated := make(map[Capability]struct{}, len(capabilities))
	for _, capability := range capabilities {
		updated[capability] = struct{}{}
	}
	s.capabilities = updated
	limit := h.config.MaxInFlightOperations
	if maxConcurrentOps > 0 && maxConcurrentOps < limit {
		limit = maxConcurrentOps
	}
	s.operationLimit = limit
	return nil
}

// Close transitions a session offline. Proxy exchanges fail immediately. An
// acknowledged lifecycle operation remains available to AwaitOperation for
// explicit reconciliation after a later registration; it is never replayed.
func (s *Session) Close() {
	s.hub.disconnect(s)
}

func (h *Hub) disconnect(s *Session) {
	var proxies []*ProxyCall
	h.mu.Lock()
	if !h.isCurrentLocked(s) || s.closed {
		h.mu.Unlock()
		return
	}
	s.closed = true
	delete(h.sessions, s.dataPlaneID)
	for _, op := range h.operations {
		if op.session == s && !op.terminal {
			op.inFlight = false
			if s.inFlight > 0 {
				s.inFlight--
			}
			if op.acknowledged {
				op.reconcilable = true
				op.notifyLocked()
			} else {
				op.terminal = true
				op.err = ErrConnectorUnavailable
				op.notifyLocked()
			}
		}
	}
	for _, proxy := range h.collectProxiesLocked(s) {
		delete(h.proxies, proxyKey(s.dataPlaneID, proxy.id))
		proxies = append(proxies, proxy)
	}
	h.mu.Unlock()
	for _, proxy := range proxies {
		proxy.fail(ErrProxyDisconnected)
	}
}

func (h *Hub) collectProxiesLocked(s *Session) []*ProxyCall {
	var proxies []*ProxyCall
	for _, proxy := range h.proxies {
		if proxy.session == s {
			proxies = append(proxies, proxy)
		}
	}
	return proxies
}

// OperationRequest names a stable operation. If ID is empty, the hub creates a
// cryptographically random opaque ID. Reusing an ID is forbidden, including
// after completion, so a delayed result can never satisfy a different call.
type OperationRequest struct {
	ID          string
	Kind        string
	Deadline    time.Time
	Payload     []byte
	ContentType string
}

type OperationState string

const (
	OperationPending              OperationState = "pending"
	OperationAcknowledged         OperationState = "acknowledged"
	OperationCancelRequested      OperationState = "cancel_requested"
	OperationReconciliationNeeded OperationState = "reconciliation_needed"
	OperationCompleted            OperationState = "completed"
)

type ResultStatus string

const (
	ResultSucceeded        ResultStatus = "succeeded"
	ResultFailed           ResultStatus = "failed"
	ResultCancelled        ResultStatus = "cancelled"
	ResultDeadlineExceeded ResultStatus = "deadline_exceeded"
)

type OperationResult struct {
	ID      string
	Status  ResultStatus
	Error   string
	Payload []byte
}

type OperationSnapshot struct {
	ID          string
	DataPlaneID string
	Generation  uint64
	State       OperationState
	Result      *OperationResult
	Err         error
}

type operation struct {
	id, dataPlaneID                                                 string
	session                                                         *Session
	generation                                                      uint64
	acknowledged, reconcilable, terminal, inFlight, cancelRequested bool
	result                                                          *OperationResult
	err                                                             error
	changed                                                         chan struct{}
}

// Every command crossing the connector boundary has a finite lifetime. HTTP
// servers do not normally put a deadline on request contexts, so leaving the
// fallback at zero would create an invalid wire message and make ordinary MCP
// proxy requests fail before they reached the data plane.
const defaultCommandTimeout = 5 * time.Minute

func (op *operation) notifyLocked() { close(op.changed); op.changed = make(chan struct{}) }

func (h *Hub) StartOperation(ctx context.Context, dataPlaneID string, request OperationRequest) (*OperationResult, error) {
	if request.Kind == "" {
		return nil, fmt.Errorf("operation kind is required")
	}
	if request.ID == "" {
		var err error
		request.ID, err = newID()
		if err != nil {
			return nil, err
		}
	}
	deadline := effectiveDeadline(ctx, request.Deadline)
	h.mu.Lock()
	session, err := h.usableSessionLocked(dataPlaneID, CapabilityOperations)
	if err == nil && session.inFlight >= session.operationLimit {
		err = ErrInFlightLimit
	}
	if err == nil {
		if _, exists := h.operations[request.ID]; exists {
			err = ErrOperationExists
		}
	}
	if err != nil {
		h.mu.Unlock()
		return nil, err
	}
	op := &operation{id: request.ID, dataPlaneID: dataPlaneID, session: session, generation: session.generation, inFlight: true, changed: make(chan struct{})}
	h.operations[request.ID] = op
	session.inFlight++
	h.mu.Unlock()
	command := Command{Kind: CommandOperationStart, DataPlaneID: dataPlaneID, InstanceID: session.instanceID, Generation: session.generation, Operation: &OperationStart{ID: request.ID, Kind: request.Kind, DeadlineUnixMilli: deadline, Payload: append([]byte(nil), request.Payload...), ContentType: request.ContentType}}
	if err := session.send(ctx, command); err != nil {
		h.failUnacknowledged(session, op, err)
		return nil, err
	}
	return h.awaitOperation(ctx, op, true)
}

func (h *Hub) failUnacknowledged(session *Session, op *operation, err error) {
	h.mu.Lock()
	if h.operations[op.id] == op && !op.acknowledged && !op.terminal {
		op.terminal, op.err, op.inFlight = true, err, false
		if op.session == session && session.inFlight > 0 {
			session.inFlight--
		}
		op.notifyLocked()
	}
	h.mu.Unlock()
	if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
		return
	}
	h.disconnect(session)
}

// AwaitOperation observes a known operation, including one left reconcilable
// by a disconnect. It never sends a new start command.
func (h *Hub) AwaitOperation(ctx context.Context, operationID string) (*OperationResult, error) {
	h.mu.Lock()
	op := h.operations[operationID]
	h.mu.Unlock()
	if op == nil {
		return nil, fmt.Errorf("unknown operation %q", operationID)
	}
	return h.awaitOperation(ctx, op, false)
}

func (h *Hub) awaitOperation(ctx context.Context, op *operation, cancelOnContext bool) (*OperationResult, error) {
	for {
		h.mu.Lock()
		if op.terminal {
			result, err := cloneResult(op.result), op.err
			h.mu.Unlock()
			return result, err
		}
		if op.reconcilable {
			h.mu.Unlock()
			return nil, ErrOperationIndeterminate
		}
		changed := op.changed
		h.mu.Unlock()
		select {
		case <-changed:
		case <-ctx.Done():
			if cancelOnContext {
				h.requestCancel(op, ctx.Err())
			}
			return nil, ctx.Err()
		}
	}
}

func (h *Hub) requestCancel(op *operation, cause error) {
	h.mu.Lock()
	if op.terminal || op.cancelRequested || op.reconcilable || !h.isCurrentLocked(op.session) {
		h.mu.Unlock()
		return
	}
	op.cancelRequested = true
	op.notifyLocked()
	session := op.session
	h.mu.Unlock()
	// A cancellation is best effort, but it gets a fresh bounded context even
	// when the caller's context is already done.
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	_ = session.send(ctx, Command{Kind: CommandOperationCancel, DataPlaneID: op.dataPlaneID, InstanceID: session.instanceID, Generation: session.generation, Cancel: &OperationCancel{ID: op.id, Reason: cause.Error()}})
}

func (s *Session) Ack(operationID string, accepted bool, rejection string) error {
	h := s.hub
	h.mu.Lock()
	defer h.mu.Unlock()
	if !h.isCurrentLocked(s) {
		return ErrStaleSession
	}
	op := h.operations[operationID]
	if op == nil || op.session != s || op.generation != s.generation || op.terminal || op.acknowledged {
		return ErrInvalidLifecycle
	}
	if !accepted {
		op.terminal, op.inFlight = true, false
		op.err = errors.New(rejection)
		if rejection == "" {
			op.err = errors.New("operation rejected")
		}
		if s.inFlight > 0 {
			s.inFlight--
		}
		op.notifyLocked()
		return nil
	}
	op.acknowledged = true
	op.notifyLocked()
	return nil
}

// Result accepts a normal current-session result, or an explicit result for a
// disconnected acknowledged operation from the current replacement session.
func (s *Session) Result(result OperationResult) error {
	if result.ID == "" || result.Status == "" {
		return ErrInvalidLifecycle
	}
	h := s.hub
	h.mu.Lock()
	defer h.mu.Unlock()
	if !h.isCurrentLocked(s) {
		return ErrStaleSession
	}
	op := h.operations[result.ID]
	if op == nil || op.terminal {
		return ErrInvalidLifecycle
	}
	if op.reconcilable {
		if op.dataPlaneID != s.dataPlaneID {
			return ErrStaleSession
		}
	} else if op.session != s || op.generation != s.generation || !op.acknowledged {
		return ErrStaleSession
	}
	op.result = cloneResult(&result)
	op.terminal, op.reconcilable, op.inFlight = true, false, false
	if op.session == s && s.inFlight > 0 {
		s.inFlight--
	}
	op.notifyLocked()
	return nil
}

func (h *Hub) Operation(operationID string) (OperationSnapshot, bool) {
	h.mu.Lock()
	defer h.mu.Unlock()
	op := h.operations[operationID]
	if op == nil {
		return OperationSnapshot{}, false
	}
	state := OperationPending
	switch {
	case op.terminal:
		state = OperationCompleted
	case op.reconcilable:
		state = OperationReconciliationNeeded
	case op.cancelRequested:
		state = OperationCancelRequested
	case op.acknowledged:
		state = OperationAcknowledged
	}
	return OperationSnapshot{ID: op.id, DataPlaneID: op.dataPlaneID, Generation: op.generation, State: state, Result: cloneResult(op.result), Err: op.err}, true
}

func (h *Hub) isCurrentLocked(s *Session) bool {
	return s != nil && !s.closed && h.sessions[s.dataPlaneID] == s
}

func (h *Hub) usableSessionLocked(dataPlaneID string, capability Capability) (*Session, error) {
	s := h.sessions[dataPlaneID]
	if s == nil || s.closed {
		return nil, ErrConnectorUnavailable
	}
	if s.draining {
		return nil, ErrConnectorDraining
	}
	if _, ok := s.capabilities[capability]; !ok {
		return nil, ErrCapabilityUnavailable
	}
	return s, nil
}

func (s *Session) send(ctx context.Context, command Command) error {
	s.sendMu.Lock()
	defer s.sendMu.Unlock()
	s.hub.mu.Lock()
	current := s.hub.isCurrentLocked(s)
	s.hub.mu.Unlock()
	if !current {
		return ErrConnectorUnavailable
	}
	if err := s.sender.Send(ctx, command); err != nil {
		return err
	}
	return nil
}

func effectiveDeadline(ctx context.Context, requested time.Time) int64 {
	deadline := requested
	if contextDeadline, ok := ctx.Deadline(); ok && (deadline.IsZero() || contextDeadline.Before(deadline)) {
		deadline = contextDeadline
	}
	if deadline.IsZero() {
		deadline = time.Now().Add(defaultCommandTimeout)
	}
	return deadline.UnixMilli()
}

func cloneResult(result *OperationResult) *OperationResult {
	if result == nil {
		return nil
	}
	copy := *result
	copy.Payload = append([]byte(nil), result.Payload...)
	return &copy
}

func newID() (string, error) {
	bytes := make([]byte, 16)
	if _, err := rand.Read(bytes); err != nil {
		return "", fmt.Errorf("generate connector ID: %w", err)
	}
	return hex.EncodeToString(bytes), nil
}
