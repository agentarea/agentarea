package connectorhub

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"
)

type recordingSender struct {
	mu       sync.Mutex
	commands []Command
	notify   chan struct{}
	err      error
}

func newRecordingSender() *recordingSender { return &recordingSender{notify: make(chan struct{}, 128)} }

func (s *recordingSender) Send(_ context.Context, command Command) error {
	s.mu.Lock()
	s.commands = append(s.commands, command)
	err := s.err
	s.mu.Unlock()
	select {
	case s.notify <- struct{}{}:
	default:
	}
	return err
}

func (s *recordingSender) commandsOf(kind CommandKind) []Command {
	s.mu.Lock()
	defer s.mu.Unlock()
	var commands []Command
	for _, command := range s.commands {
		if command.Kind == kind {
			commands = append(commands, command)
		}
	}
	return commands
}

func waitFor(t *testing.T, timeout time.Duration, condition func() bool) {
	t.Helper()
	deadline := time.NewTimer(timeout)
	defer deadline.Stop()
	for !condition() {
		select {
		case <-deadline.C:
			t.Fatal("timed out waiting for condition")
		case <-time.After(time.Millisecond):
		}
	}
}

func register(t *testing.T, h *Hub, sender Sender, id string) *Session {
	t.Helper()
	session, err := h.Register(Registration{DataPlaneID: "dp-a", ConnectorInstanceID: id, Capabilities: []Capability{CapabilityOperations, CapabilityProxy}, Sender: sender})
	if err != nil {
		t.Fatalf("register: %v", err)
	}
	return session
}

func TestOperationAckResultAndConcurrentCalls(t *testing.T) {
	hub := New(Config{MaxInFlightOperations: 24})
	sender := newRecordingSender()
	session := register(t, hub, sender, "one")

	const calls = 20
	results := make(chan error, calls)
	for i := 0; i < calls; i++ {
		go func() {
			result, err := hub.StartOperation(context.Background(), "dp-a", OperationRequest{Kind: "start"})
			if err != nil || result == nil || result.Status != ResultSucceeded {
				results <- errors.New("operation did not succeed")
				return
			}
			results <- nil
		}()
	}
	waitFor(t, time.Second, func() bool { return len(sender.commandsOf(CommandOperationStart)) == calls })
	for _, command := range sender.commandsOf(CommandOperationStart) {
		if err := session.Ack(command.Operation.ID, true, ""); err != nil {
			t.Fatalf("ack: %v", err)
		}
		if err := session.Result(OperationResult{ID: command.Operation.ID, Status: ResultSucceeded}); err != nil {
			t.Fatalf("result: %v", err)
		}
	}
	for i := 0; i < calls; i++ {
		if err := <-results; err != nil {
			t.Fatal(err)
		}
	}
}

func TestDuplicateConnectorRequiresClose(t *testing.T) {
	hub := New(Config{})
	first := register(t, hub, newRecordingSender(), "one")
	if _, err := hub.Register(Registration{DataPlaneID: "dp-a", ConnectorInstanceID: "two", Sender: newRecordingSender()}); !errors.Is(err, ErrConnectorActive) {
		t.Fatalf("duplicate registration error = %v", err)
	}
	first.Close()
	second := register(t, hub, newRecordingSender(), "two")
	if second.Generation() != first.Generation()+1 {
		t.Fatalf("generation = %d, want %d", second.Generation(), first.Generation()+1)
	}
}

func TestDisconnectAcknowledgedOperationIsReconciledOnlyByReplacement(t *testing.T) {
	hub := New(Config{})
	firstSender := newRecordingSender()
	first := register(t, hub, firstSender, "one")
	done := make(chan error, 1)
	go func() {
		_, err := hub.StartOperation(context.Background(), "dp-a", OperationRequest{ID: "op-a", Kind: "start"})
		done <- err
	}()
	waitFor(t, time.Second, func() bool { return len(firstSender.commandsOf(CommandOperationStart)) == 1 })
	if err := first.Ack("op-a", true, ""); err != nil {
		t.Fatal(err)
	}
	first.Close()
	if err := <-done; !errors.Is(err, ErrOperationIndeterminate) {
		t.Fatalf("disconnect error = %v", err)
	}
	if snapshot, ok := hub.Operation("op-a"); !ok || snapshot.State != OperationReconciliationNeeded {
		t.Fatalf("snapshot = %#v, exists=%v", snapshot, ok)
	}

	second := register(t, hub, newRecordingSender(), "two")
	if err := first.Result(OperationResult{ID: "op-a", Status: ResultSucceeded}); !errors.Is(err, ErrStaleSession) {
		t.Fatalf("stale result = %v", err)
	}
	if err := second.Result(OperationResult{ID: "op-a", Status: ResultSucceeded}); err != nil {
		t.Fatalf("replacement reconciliation: %v", err)
	}
	result, err := hub.AwaitOperation(context.Background(), "op-a")
	if err != nil || result.Status != ResultSucceeded {
		t.Fatalf("reconciled result = %#v, %v", result, err)
	}
}

func TestContextCancelSendsOperationCancel(t *testing.T) {
	hub := New(Config{})
	sender := newRecordingSender()
	_ = register(t, hub, sender, "one")
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Millisecond)
	defer cancel()
	_, err := hub.StartOperation(ctx, "dp-a", OperationRequest{ID: "op-timeout", Kind: "start"})
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("operation error = %v", err)
	}
	waitFor(t, time.Second, func() bool { return len(sender.commandsOf(CommandOperationCancel)) == 1 })
	cancelCommand := sender.commandsOf(CommandOperationCancel)[0]
	if cancelCommand.Cancel.ID != "op-timeout" {
		t.Fatalf("cancel ID = %q", cancelCommand.Cancel.ID)
	}
	start := sender.commandsOf(CommandOperationStart)[0]
	if start.Operation.DeadlineUnixMilli == 0 {
		t.Fatal("deadline was not propagated")
	}
}

func TestEffectiveDeadlineDefaultsForBackgroundContext(t *testing.T) {
	before := time.Now().Add(defaultCommandTimeout - time.Second).UnixMilli()
	deadline := effectiveDeadline(context.Background(), time.Time{})
	after := time.Now().Add(defaultCommandTimeout + time.Second).UnixMilli()
	if deadline < before || deadline > after {
		t.Fatalf("default deadline %d is outside [%d, %d]", deadline, before, after)
	}
}

func TestOperationInFlightBound(t *testing.T) {
	hub := New(Config{MaxInFlightOperations: 1})
	sender := newRecordingSender()
	session := register(t, hub, sender, "one")
	done := make(chan error, 1)
	go func() {
		_, err := hub.StartOperation(context.Background(), "dp-a", OperationRequest{ID: "first", Kind: "start"})
		done <- err
	}()
	waitFor(t, time.Second, func() bool { return len(sender.commandsOf(CommandOperationStart)) == 1 })
	if _, err := hub.StartOperation(context.Background(), "dp-a", OperationRequest{ID: "second", Kind: "start"}); !errors.Is(err, ErrInFlightLimit) {
		t.Fatalf("in-flight limit error = %v", err)
	}
	if err := session.Ack("first", true, ""); err != nil {
		t.Fatal(err)
	}
	if err := session.Result(OperationResult{ID: "first", Status: ResultSucceeded}); err != nil {
		t.Fatal(err)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
}

func TestProxyBackpressureDisconnectAndStaleGeneration(t *testing.T) {
	hub := New(Config{PerStreamBuffer: 1})
	firstSender := newRecordingSender()
	first := register(t, hub, firstSender, "one")
	proxy, err := hub.OpenProxy(context.Background(), "dp-a", ProxyRequest{ID: "request-a", Method: "GET", Path: "/health"})
	if err != nil {
		t.Fatal(err)
	}
	if err := first.ProxyChunk("request-a", 0, []byte("one")); err != nil {
		t.Fatal(err)
	}
	if err := first.ProxyChunk("request-a", 1, []byte("two")); !errors.Is(err, ErrStreamBackpressure) {
		t.Fatalf("backpressure = %v", err)
	}
	chunk, err := proxy.Read(context.Background())
	if err != nil || string(chunk) != "one" {
		t.Fatalf("first chunk = %q, %v", chunk, err)
	}
	_, err = proxy.Read(context.Background())
	if !errors.Is(err, ErrStreamBackpressure) {
		t.Fatalf("read after overflow = %v", err)
	}
	waitFor(t, time.Second, func() bool { return len(firstSender.commandsOf(CommandProxyEnd)) == 1 })

	// A disconnect clears all proxy exchanges immediately and an old session
	// cannot emit into a new generation, even if the request ID is reused.
	proxy, err = hub.OpenProxy(context.Background(), "dp-a", ProxyRequest{ID: "request-b", Method: "GET", Path: "/"})
	if err != nil {
		t.Fatal(err)
	}
	first.Close()
	_, err = proxy.Read(context.Background())
	if !errors.Is(err, ErrProxyDisconnected) {
		t.Fatalf("disconnect read = %v", err)
	}
	second := register(t, hub, newRecordingSender(), "two")
	newProxy, err := hub.OpenProxy(context.Background(), "dp-a", ProxyRequest{ID: "request-b", Method: "GET", Path: "/"})
	if err != nil {
		t.Fatal(err)
	}
	if err := first.ProxyChunk("request-b", 0, []byte("stale")); !errors.Is(err, ErrStaleSession) {
		t.Fatalf("stale proxy chunk = %v", err)
	}
	if err := second.ProxyChunk("request-b", 0, []byte("fresh")); err != nil {
		t.Fatal(err)
	}
	chunk, err = newProxy.Read(context.Background())
	if err != nil || string(chunk) != "fresh" {
		t.Fatalf("fresh chunk = %q, %v", chunk, err)
	}
}

func TestConcurrentProxyWritesPreserveSequenceOnTransport(t *testing.T) {
	hub := New(Config{})
	sender := newRecordingSender()
	_ = register(t, hub, sender, "one")
	proxy, err := hub.OpenProxy(context.Background(), "dp-a", ProxyRequest{ID: "ordered", Method: "POST", Path: "/"})
	if err != nil {
		t.Fatal(err)
	}
	const writes = 16
	var group sync.WaitGroup
	group.Add(writes)
	for i := 0; i < writes; i++ {
		go func() {
			defer group.Done()
			if err := proxy.Write(context.Background(), []byte("x")); err != nil {
				t.Errorf("write: %v", err)
			}
		}()
	}
	group.Wait()
	chunks := sender.commandsOf(CommandProxyChunk)
	if len(chunks) != writes {
		t.Fatalf("sent %d chunks, want %d", len(chunks), writes)
	}
	for i, command := range chunks {
		if command.Chunk.Sequence != uint64(i) {
			t.Fatalf("transport sequence[%d] = %d", i, command.Chunk.Sequence)
		}
	}
}

func TestDuplicateProxyEndIsIdempotentForCurrentSession(t *testing.T) {
	hub := New(Config{})
	session := register(t, hub, newRecordingSender(), "one")
	if _, err := hub.OpenProxy(context.Background(), "dp-a", ProxyRequest{ID: "completed", Method: "GET", Path: "/"}); err != nil {
		t.Fatal(err)
	}
	if err := session.ProxyEnd("completed", "complete"); err != nil {
		t.Fatal(err)
	}
	if err := session.ProxyEnd("completed", "complete"); err != nil {
		t.Fatalf("duplicate terminal frame = %v", err)
	}
	if err := session.ProxyEnd("never-admitted", "complete"); !errors.Is(err, ErrStaleSession) {
		t.Fatalf("unknown terminal frame = %v", err)
	}
}

func TestDrainGatesNewCallsButNotExistingOperation(t *testing.T) {
	hub := New(Config{})
	sender := newRecordingSender()
	session := register(t, hub, sender, "one")
	done := make(chan error, 1)
	go func() {
		_, err := hub.StartOperation(context.Background(), "dp-a", OperationRequest{ID: "existing", Kind: "start"})
		done <- err
	}()
	waitFor(t, time.Second, func() bool { return len(sender.commandsOf(CommandOperationStart)) == 1 })
	if err := session.Ack("existing", true, ""); err != nil {
		t.Fatal(err)
	}
	if err := session.SetDraining(true); err != nil {
		t.Fatal(err)
	}
	if _, err := hub.StartOperation(context.Background(), "dp-a", OperationRequest{ID: "new", Kind: "start"}); !errors.Is(err, ErrConnectorDraining) {
		t.Fatalf("drained operation = %v", err)
	}
	if _, err := hub.OpenProxy(context.Background(), "dp-a", ProxyRequest{ID: "new-proxy", Method: "GET", Path: "/"}); !errors.Is(err, ErrConnectorDraining) {
		t.Fatalf("drained proxy = %v", err)
	}
	if err := session.Result(OperationResult{ID: "existing", Status: ResultSucceeded}); err != nil {
		t.Fatal(err)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
}
