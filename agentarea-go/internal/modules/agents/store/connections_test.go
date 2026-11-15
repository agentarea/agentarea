package store

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestLocateClientOnlyAmongTheGivenWorkspaces(t *testing.T) {
	ctx := context.Background()
	pool, s, other := session(t)
	id := uuid.New()
	if err := (Clients{}).Insert(ctx, s, id, "u1", "Codex", nil, "codex", time.Now()); err != nil {
		t.Fatal(err)
	}
	ws, ok, err := LocateClient(ctx, pool, id, []string{other.Workspace().ID(), s.Workspace().ID()})
	if err != nil || !ok || ws != s.Workspace().ID() {
		t.Fatalf("located %q %v %v", ws, ok, err)
	}
	if _, ok, err := LocateClient(ctx, pool, id, []string{other.Workspace().ID()}); err != nil || ok {
		t.Fatalf("found outside the allowlist: %v %v", ok, err)
	}
	if _, ok, err := LocateClient(ctx, pool, uuid.New(), []string{s.Workspace().ID()}); err != nil || ok {
		t.Fatalf("unknown client: %v %v", ok, err)
	}
}
