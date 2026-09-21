package sandboxruntime

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestFailedE2BBootstrapRetainsEarlierAllocationObservation(t *testing.T) {
	enteredBootstrap := make(chan time.Time, 1)
	releaseBootstrap := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/sandboxes":
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"sandboxID":"allocated-before-bootstrap","envdVersion":"0.1.0"}`))
		case "/filesystem.Filesystem/MakeDir":
			enteredBootstrap <- time.Now().UTC()
			select {
			case <-releaseBootstrap:
				http.Error(w, "bootstrap failed", http.StatusBadRequest)
			case <-r.Context().Done():
			}
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	provider, err := NewE2BProvider(testE2BConfig("e2b", server.URL))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	type createResult struct {
		session *Session
		err     error
	}
	result := make(chan createResult, 1)
	go func() {
		session, err := provider.Create(ctx, CreateRequest{
			WorkspaceID: "workspace-1", TaskID: "task-1", ProvisioningID: "provision-1",
		})
		result <- createResult{session: session, err: err}
	}()
	var bootstrapAt time.Time
	select {
	case bootstrapAt = <-enteredBootstrap:
	case <-ctx.Done():
		t.Fatal("bootstrap was not reached")
	}
	close(releaseBootstrap)
	created := <-result
	if created.err == nil || created.session == nil {
		t.Fatalf("failed initialization lost allocation: %+v", created)
	}
	if created.session.CreatedAt.IsZero() || created.session.CreatedAt.After(bootstrapAt) {
		t.Fatalf("allocation timestamp %s did not precede initialization at %s", created.session.CreatedAt, bootstrapAt)
	}
	manager, _ := newTestManager(t)
	manager.provider = provider
	manager.bindSessionIdentity(created.session, "workspace-1", "task-1")
	recorder := &lifecycleRecorder{}
	manager.SetUsageRecorder(recorder)
	if err := manager.recordAllocation(ctx, created.session); err != nil {
		t.Fatal(err)
	}
	for _, event := range recorder.events {
		var payload map[string]json.RawMessage
		if err := json.Unmarshal(event.Data, &payload); err != nil {
			t.Fatal(err)
		}
		if _, exists := payload["started_at"]; exists {
			t.Fatal("observation was falsely labelled exact provider start")
		}
		if string(payload["timestamp_source"]) != `"provider_create_response_observed"` {
			t.Fatalf("timestamp provenance = %s", payload["timestamp_source"])
		}
		var observed time.Time
		if err := json.Unmarshal(payload["allocation_observed_at"], &observed); err != nil {
			t.Fatal(err)
		}
		if !observed.Equal(created.session.CreatedAt) {
			t.Fatal("allocation observation changed during manager binding")
		}
	}
}

func TestOpaqueProvisioningFailureDoesNotInventPhysicalAllocation(t *testing.T) {
	manager, provider := newTestManager(t)
	provider.createErr = errors.New("opaque SDK initialization failure: secret-token")
	provider.createReturnsNil = true
	recorder := &lifecycleRecorder{}
	manager.SetUsageRecorder(recorder)
	if _, err := manager.ensure(context.Background(), "workspace-1", "task-1"); err == nil {
		t.Fatal("opaque provisioning failure was hidden")
	}
	observed := make(map[string]map[string]json.RawMessage)
	for _, event := range recorder.events {
		if strings.Contains(string(event.Data), "secret-token") {
			t.Fatal("provider error leaked into usage")
		}
		if event.Kind == "sandbox.allocated" {
			t.Fatal("invented physical allocation for opaque provider response")
		}
		if event.ResourceKind != "sandbox_provisioning" || event.IncarnationID != "" || event.ResourceID != "workspace-1/task-1" {
			t.Fatalf("provisioning attempt invented physical identity: %+v", event)
		}
		var payload map[string]json.RawMessage
		if err := json.Unmarshal(event.Data, &payload); err != nil {
			t.Fatal(err)
		}
		if string(payload["allocation_visibility"]) != `"unavailable"` {
			t.Fatalf("opaque visibility = %s", payload["allocation_visibility"])
		}
		if _, exists := payload["provider_resources"]; exists {
			t.Fatal("invented resource quantity for opaque provider response")
		}
		if _, exists := payload["started_at"]; exists {
			t.Fatal("attempt timestamp mislabeled physical lifetime")
		}
		observed[event.Kind] = payload
	}
	started, failed := observed["sandbox.provisioning_started"], observed["sandbox.provisioning_failed"]
	if started == nil || failed == nil {
		t.Fatalf("missing bounded provisioning observations: %v", observed)
	}
	if string(started["operation_id"]) != string(failed["operation_id"]) {
		t.Fatal("provisioning result lost its operation identity")
	}
	var requestAt, responseAt time.Time
	if err := json.Unmarshal(started["request_observed_at"], &requestAt); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(failed["response_observed_at"], &responseAt); err != nil {
		t.Fatal(err)
	}
	if responseAt.Before(requestAt) {
		t.Fatal("provisioning response precedes request")
	}
}
