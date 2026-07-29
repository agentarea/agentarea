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

// handleInstanceCreated must not provision anything: Python verify() owns
// provisioning via POST /instances.
func TestHandleInstanceCreated_DoesNotCallProvider(t *testing.T) {
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

	sub.handleInstanceCreated(payload)

	if backend.createCalled {
		t.Error("handleInstanceCreated must not call CreateInstance on any backend provider")
	}
}

// The no-op contract holds regardless of parse outcome.
func TestHandleInstanceCreated_MalformedPayload_NoopNoPanic(t *testing.T) {
	backend := &stubBackend{}
	sub := newTestSubscriber(backend)

	sub.handleInstanceCreated("not-json-at-all")

	if backend.createCalled {
		t.Error("handleInstanceCreated must not call CreateInstance on malformed payload")
	}
}

// A payload that is not the shared CloudEvents format is dropped rather than
// dispatched to any provider.
func TestHandleInstanceDeleted_MalformedPayload_DoesNotCallProvider(t *testing.T) {
	backend := &stubBackend{}
	sub := newTestSubscriber(backend)

	sub.handleInstanceDeleted(context.Background(), "not-json-at-all")

	if backend.deleteCalled {
		t.Error("handleInstanceDeleted must not call DeleteInstance on malformed payload")
	}
}

// instance_id is required; without it there is nothing to delete.
func TestHandleInstanceDeleted_MissingInstanceID_DoesNotCallProvider(t *testing.T) {
	backend := &stubBackend{}
	sub := newTestSubscriber(backend)

	payload := `{
		"specversion": "1.0",
		"type": "com.agentarea.mcp.instance.deleted",
		"source": "/python",
		"id": "abc-123",
		"time": "2026-04-24T00:00:00Z",
		"data": {"name": "my-server"}
	}`

	sub.handleInstanceDeleted(context.Background(), payload)

	if backend.deleteCalled {
		t.Error("handleInstanceDeleted must not call DeleteInstance without an instance_id")
	}
}
