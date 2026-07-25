package activationauth

import (
	"strings"
	"testing"
	"time"
)

func TestTokenIsScopedBoundAndExpires(t *testing.T) {
	secret := []byte(strings.Repeat("s", 32))
	now := time.Unix(1_700_000_000, 0)
	identity := Identity{WorkspaceID: "workspace-1", TaskID: "task-1", Generation: 3, FencingToken: 9}
	bodyDigest := BodySHA256([]byte(`{"command_path":"command.sh"}`))
	token, err := Sign(secret, ScopeExecute, identity, bodyDigest, now, time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	if err := Verify(token, secret, ScopeExecute, identity, bodyDigest, now.Add(30*time.Second)); err != nil {
		t.Fatalf("Verify() error = %v", err)
	}
	wrong := identity
	wrong.TaskID = "task-2"
	if err := Verify(token, secret, ScopeExecute, wrong, bodyDigest, now); err == nil {
		t.Fatal("token was accepted for another task")
	}
	if err := Verify(token, secret, ScopeWriteback, identity, bodyDigest, now); err == nil {
		t.Fatal("execute token was accepted for writeback")
	}
	if err := Verify(token, secret, ScopeExecute, identity, bodyDigest, now.Add(time.Minute)); err == nil {
		t.Fatal("expired token was accepted")
	}
	if err := Verify(token, secret, ScopeExecute, identity, BodySHA256([]byte(`{"command_path":"other.sh"}`)), now); err == nil {
		t.Fatal("token was accepted for an altered request body")
	}
}

func TestTamperedTokenIsRejected(t *testing.T) {
	secret := []byte(strings.Repeat("s", 32))
	identity := Identity{WorkspaceID: "workspace-1", TaskID: "task-1", Generation: 1, FencingToken: 1}
	bodyDigest := BodySHA256([]byte("body"))
	token, err := Sign(secret, ScopeExecute, identity, bodyDigest, time.Now(), time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	if err := Verify(token+"x", secret, ScopeExecute, identity, bodyDigest, time.Now()); err == nil {
		t.Fatal("tampered token was accepted")
	}
}
