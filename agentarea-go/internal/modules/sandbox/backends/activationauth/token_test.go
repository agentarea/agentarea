package activationauth

import (
	"errors"
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

func TestFileTransferTokenIsBoundToMethodPathSizeAndDigest(t *testing.T) {
	secret := []byte(strings.Repeat("s", 32))
	now := time.Unix(1_700_000_000, 0)
	identity := Identity{WorkspaceID: "workspace-1", TaskID: "task-1", FencingToken: 1}
	contentDigest := BodySHA256([]byte("body"))
	binding := TransferSHA256("PUT", "inputs/a.txt", 4, 0o600, contentDigest)
	token, err := Sign(secret, ScopeFiles, identity, binding, now, time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	for name, changed := range map[string]string{
		"method": TransferSHA256("GET", "inputs/a.txt", 4, 0o600, contentDigest),
		"path":   TransferSHA256("PUT", "inputs/b.txt", 4, 0o600, contentDigest),
		"size":   TransferSHA256("PUT", "inputs/a.txt", 5, 0o600, contentDigest),
		"mode":   TransferSHA256("PUT", "inputs/a.txt", 4, 0o755, contentDigest),
		"digest": TransferSHA256("PUT", "inputs/a.txt", 4, 0o600, BodySHA256([]byte("else"))),
	} {
		t.Run(name, func(t *testing.T) {
			if err := Verify(token, secret, ScopeFiles, identity, changed, now); err == nil {
				t.Fatal("transfer token accepted changed operation")
			}
		})
	}
}

func TestStorageTokenGrantsOneInstanceOfOneWorkspace(t *testing.T) {
	secret := []byte(strings.Repeat("s", 32))
	now := time.Unix(1_700_000_000, 0)
	identity := Identity{WorkspaceID: "workspace-1", InstanceID: "instance-1"}
	binding := BodySHA256(nil)
	token, err := Sign(secret, ScopeStorage, identity, binding, now, 30*24*time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	if err := Verify(token, secret, ScopeStorage, identity, binding, now.Add(29*24*time.Hour)); err != nil {
		t.Fatalf("Verify() error = %v", err)
	}
	for name, other := range map[string]Identity{
		"instance":  {WorkspaceID: "workspace-1", InstanceID: "instance-2"},
		"workspace": {WorkspaceID: "workspace-2", InstanceID: "instance-1"},
	} {
		if err := Verify(token, secret, ScopeStorage, other, binding, now); !errors.Is(err, ErrClaimsMismatch) {
			t.Fatalf("%s: Verify() error = %v, want ErrClaimsMismatch", name, err)
		}
	}
	if err := Verify(token, secret, ScopeFiles, identity, binding, now); !errors.Is(err, ErrClaimsMismatch) {
		t.Fatalf("storage token was accepted for files: %v", err)
	}
	for _, incomplete := range []Identity{
		{WorkspaceID: "workspace-1"},
		{WorkspaceID: "workspace-1", InstanceID: "instance-1", TaskID: "task-1"},
		{WorkspaceID: "workspace-1", InstanceID: "instance-1", FencingToken: 1},
	} {
		if _, err := Sign(secret, ScopeStorage, incomplete, binding, now, time.Hour); err == nil {
			t.Fatalf("Sign() accepted storage identity %+v", incomplete)
		}
	}
	if _, err := Sign(secret, ScopeFiles, Identity{WorkspaceID: "workspace-1", TaskID: "task-1", InstanceID: "instance-1", FencingToken: 1}, binding, now, time.Hour); err == nil {
		t.Fatal("Sign() accepted an instance id on a task scope")
	}
}
