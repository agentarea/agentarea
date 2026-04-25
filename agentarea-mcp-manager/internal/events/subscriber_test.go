package events

import (
	"context"
	"io"
	"log/slog"
	"testing"

	"github.com/agentarea/mcp-manager/internal/providers"
)

// stubBackend satisfies providers.Backend without touching any real infra.
// It records whether CreateInstance was called so tests can assert it never is.
type stubBackend struct {
	createCalled bool
	deleteCalled bool
}

func (b *stubBackend) CreateInstance(_ context.Context, _ *providers.BackendInstanceSpec) (*providers.BackendInstanceResult, error) {
	b.createCalled = true
	return &providers.BackendInstanceResult{ID: "stub", Status: "running"}, nil
}

func (b *stubBackend) DeleteInstance(_ context.Context, _ string) error {
	b.deleteCalled = true
	return nil
}

func newTestSubscriber(backend *stubBackend) *EventSubscriber {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	kubeProvider := providers.NewKubernetesProvider(backend, logger)
	pm := providers.NewProviderManager(nil, kubeProvider, nil)
	return &EventSubscriber{
		redisClient:     nil, // not needed for unit tests
		providerManager: pm,
		logger:          logger,
	}
}

// tryHandleInstanceCreated must return true (signals "handled") without
// invoking CreateInstance on any provider.
func TestTryHandleInstanceCreated_ReturnsTrue_WithoutCallingProvider(t *testing.T) {
	backend := &stubBackend{}
	sub := newTestSubscriber(backend)

	payload := `{
		"specversion": "1.0",
		"type": "com.agentarea.mcp.instance.created",
		"source": "/python",
		"id": "abc-123",
		"time": "2026-04-24T00:00:00Z",
		"data": {
			"instance_id": "inst-abc",
			"name": "my-server"
		}
	}`

	handled := sub.tryHandleInstanceCreated(context.Background(), payload)

	if !handled {
		t.Error("tryHandleInstanceCreated must return true so the caller skips the legacy path")
	}
	if backend.createCalled {
		t.Error("tryHandleInstanceCreated must not call CreateInstance on any backend provider")
	}
}

// tryHandleInstanceCreated must also return true for a malformed payload
// (the no-op contract holds regardless of parse outcome).
func TestTryHandleInstanceCreated_MalformedPayload_StillReturnsTrue(t *testing.T) {
	backend := &stubBackend{}
	sub := newTestSubscriber(backend)

	handled := sub.tryHandleInstanceCreated(context.Background(), "not-json-at-all")

	if !handled {
		t.Error("tryHandleInstanceCreated must return true even for malformed payloads")
	}
	if backend.createCalled {
		t.Error("tryHandleInstanceCreated must not call CreateInstance on malformed payload")
	}
}

// handleLegacyInstanceCreated is a no-op: it must not call CreateInstance on
// any backend provider regardless of payload content.
func TestHandleLegacyInstanceCreated_IsNoop_DoesNotCallProvider(t *testing.T) {
	backend := &stubBackend{}
	sub := newTestSubscriber(backend)

	legacyPayload := `{
		"data": "{\"event_id\":\"e1\",\"timestamp\":\"2026-04-24T00:00:00Z\",\"event_type\":\"MCPServerInstanceCreated\",\"data\":{\"instance_id\":\"inst-xyz\",\"name\":\"test-server\",\"json_spec\":{\"type\":\"docker\",\"image\":\"nginx:alpine\",\"port\":80}}}",
		"headers": {}
	}`

	sub.handleLegacyInstanceCreated(context.Background(), legacyPayload)

	if backend.createCalled {
		t.Error("handleLegacyInstanceCreated must be a no-op and must not call CreateInstance")
	}
}

// handleLegacyInstanceCreated must not panic on an empty payload.
func TestHandleLegacyInstanceCreated_EmptyPayload_NoopNoPanic(t *testing.T) {
	backend := &stubBackend{}
	sub := newTestSubscriber(backend)

	// Should not panic
	sub.handleLegacyInstanceCreated(context.Background(), "")

	if backend.createCalled {
		t.Error("handleLegacyInstanceCreated must not call CreateInstance for empty payload")
	}
}
