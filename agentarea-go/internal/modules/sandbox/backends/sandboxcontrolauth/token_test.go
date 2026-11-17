package sandboxcontrolauth

import (
	"strings"
	"testing"
	"time"
)

func TestTokenBindsScopeWorkspaceTaskExecutionAndBody(t *testing.T) {
	secret := []byte(strings.Repeat("s", 48))
	now := time.Unix(1_900_000_000, 0).UTC()
	identity := Identity{WorkspaceID: "workspace-1", TaskID: "task-1", ExecutionID: "sexec-1"}
	digest := BodySHA256(nil)
	token, err := Sign(secret, ScopeRead, identity, digest, now, time.Minute, "0123456789abcdef")
	if err != nil {
		t.Fatal(err)
	}
	if err := Verify(token, secret, ScopeRead, identity, digest, now); err != nil {
		t.Fatalf("Verify() error = %v", err)
	}
	for name, changed := range map[string]Identity{
		"workspace": {WorkspaceID: "workspace-2", TaskID: identity.TaskID, ExecutionID: identity.ExecutionID},
		"task":      {WorkspaceID: identity.WorkspaceID, TaskID: "task-2", ExecutionID: identity.ExecutionID},
		"execution": {WorkspaceID: identity.WorkspaceID, TaskID: identity.TaskID, ExecutionID: "sexec-2"},
	} {
		t.Run(name, func(t *testing.T) {
			if err := Verify(token, secret, ScopeRead, changed, digest, now); err == nil {
				t.Fatal("changed identity was accepted")
			}
		})
	}
	if err := Verify(token, secret, ScopeCancel, identity, digest, now); err == nil {
		t.Fatal("changed scope was accepted")
	}
	if err := Verify(token, secret, ScopeRead, identity, BodySHA256([]byte("changed")), now); err == nil {
		t.Fatal("changed body was accepted")
	}
}

func TestTokenFailsClosedForMissingSecretAndExpiration(t *testing.T) {
	now := time.Unix(1_900_000_000, 0).UTC()
	identity := Identity{WorkspaceID: "workspace-1", TaskID: "task-1"}
	digest := BodySHA256([]byte("{}"))
	secret := []byte(strings.Repeat("s", 48))
	token, err := Sign(secret, ScopeCreate, identity, digest, now, time.Second, "0123456789abcdef")
	if err != nil {
		t.Fatal(err)
	}
	if err := Verify(token, nil, ScopeCreate, identity, digest, now); err == nil {
		t.Fatal("missing secret was accepted")
	}
	if err := Verify(token, secret, ScopeCreate, identity, digest, now.Add(2*time.Second)); err == nil {
		t.Fatal("expired token was accepted")
	}
}
