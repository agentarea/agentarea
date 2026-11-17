//go:build suite

package runs

import (
	"errors"
	"io"
	"net/http"
	"testing"
	"time"

	h "github.com/agentarea/agentarea/agentarea-platform/test/suite/harness"
)

// runnerKey makes a codex client and issues its runner key.
func runnerKey(t *testing.T, w *h.Workspace) (clientID, key string) {
	t.Helper()
	clientID = w.Owner.Post(t, w.Path("/clients/"), map[string]any{"name": "Laptop", "kind": "codex"}).
		Expect(http.StatusCreated).Object()["id"].(string)
	key = w.Owner.Post(t, w.Path("/clients/"+clientID+"/runner-keys"), nil).
		Expect(http.StatusCreated).Object()["key"].(string)
	return clientID, key
}

func TestWhoamiNamesTheRunnersClient(t *testing.T) {
	w := h.NewWorkspace(t)
	clientID, key := runnerKey(t, w)
	h.Bearer(t, "runner", key).Get(t, "/v1/runner/whoami").Expect(http.StatusOK).
		Match(map[string]any{"client_id": clientID, "workspace": h.AnyString, "kind": "codex"})
	w.Owner.Get(t, "/v1/runner/whoami").Expect(http.StatusForbidden).
		Match(h.Problem(http.StatusForbidden, "permission_denied", "Only a runner key is accepted"))
	h.Anonymous(t).Get(t, "/v1/runner/whoami").Expect(http.StatusUnauthorized)
}

func TestUploadRefusesATaskNotTheRunners(t *testing.T) {
	w := h.NewWorkspace(t)
	_, key := runnerKey(t, w)
	runner := h.Bearer(t, "runner", key)
	runner.Do(t, h.Request{Method: http.MethodPut, Path: "/v1/runner/tasks/" + missingTask + "/files/out.txt", Body: []byte("x")}).
		Expect(http.StatusNotFound).Match(h.Problem(http.StatusNotFound, "not_found", "Task not found"))
}

func TestSocketTakesOnlyARunnerKey(t *testing.T) {
	w := h.NewWorkspace(t)
	_, err := w.Owner.TryDialWS(t, "/v1/runner/connect", nil)
	var refused *h.WSHandshakeError
	if !errors.As(err, &refused) || refused.Status != http.StatusForbidden {
		t.Fatalf("a member's socket: %v", err)
	}
}

func TestSocketWelcomesARunnerThatSaysHello(t *testing.T) {
	w := h.NewWorkspace(t)
	clientID, key := runnerKey(t, w)
	ws := h.Bearer(t, "runner", key).DialWS(t, "/v1/runner/connect", nil)
	ws.WriteJSON(map[string]any{"type": "hello", "capacity": 1, "version": "suite",
		"models": []any{map[string]any{"name": "gpt-5", "reasoning_levels": []any{"low"}}}, "default_model": "gpt-5"})
	var welcome map[string]any
	ws.ReadJSON(10*time.Second, &welcome)
	if err := h.Compare(welcome, map[string]any{"type": "welcome", "client_id": clientID, "workspace": h.AnyString,
		"kind": "codex", "ping_seconds": 10.0, "lease_seconds": 30.0, "turns": []any{}}); err != nil {
		t.Fatal(err)
	}
	ws.WriteJSON(map[string]any{"type": "ping"})
	ws.WriteJSON(map[string]any{"type": "nope"})
	if _, _, err := ws.Read(10 * time.Second); !errors.Is(err, io.EOF) || ws.CloseCode != 1003 {
		t.Fatalf("a bad frame: %v (close %d)", err, ws.CloseCode)
	}
}
