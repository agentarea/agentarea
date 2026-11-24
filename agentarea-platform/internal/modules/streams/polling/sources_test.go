package polling

import (
	"context"
	"log/slog"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store/storetest"
)

type noInstances struct{}

func (noInstances) MCPInstanceExists(context.Context, scope.Workspace, string) (bool, error) {
	return false, nil
}

func TestASourceTheCatalogCannotDescribeIsLoadedHeld(t *testing.T) {
	ctx := context.Background()
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	stream, known, missing, bare, unreadable := uuid.New(), uuid.New(), uuid.New(), uuid.New(), uuid.New()
	exec := func(sql string, args ...any) {
		t.Helper()
		if _, err := pool.Exec(ctx, sql, args...); err != nil {
			t.Fatal(err)
		}
	}
	exec(`INSERT INTO streams (id, workspace_id, created_by, name, kind) VALUES ($1, $2, 'u1', 's', 'inbound')`, stream, ws.ID())
	insert := `INSERT INTO stream_sources (id, workspace_id, created_by, stream_id, kind, webhook_id, webhook_type, webhook_config, credential_key, registered_url)
		VALUES ($1, $2, 'u1', $3, 'webhook', $4, $5, $6::json, $7, 'https://api.example/webhooks/x')`
	exec(insert, known, ws.ID(), stream, "w-"+known.String()[:8], "chat", `{}`, uuid.New())
	exec(insert, missing, ws.ID(), stream, "w-"+missing.String()[:8], "gone", `{}`, uuid.New())
	exec(insert, bare, ws.ID(), stream, "w-"+bare.String()[:8], "plain", `{}`, uuid.New())
	exec(insert, unreadable, ws.ID(), stream, "w-"+unreadable.String()[:8], "chat", `"not an object"`, uuid.New())

	entries := func(context.Context) (map[string]EntryOf, error) {
		reg := &Registration{Register: &Request{URL: "https://chat.example/set"}, Unregister: &Request{URL: "https://chat.example/delete"}}
		return map[string]EntryOf{
			"chat":  {Entry: Entry{Slug: "chat", Registration: reg}, Spec: "chat"},
			"plain": {Entry: Entry{Slug: "plain"}, Spec: "plain"},
		}, nil
	}
	s := StoredSources{DB: storetest.DB{Pool: pool}, Entries: entries, Instances: noInstances{}, Log: slog.New(slog.DiscardHandler)}
	loaded, err := s.Load(ctx)
	if err != nil {
		t.Fatal(err)
	}
	got := map[string]Source{}
	for _, src := range loaded {
		got[src.ID] = src
	}
	if k, ok := got[known.String()]; !ok || k.Held || k.Entry.Registration == nil {
		t.Fatalf("known = %+v", k)
	}
	for name, id := range map[string]uuid.UUID{"missing type": missing, "type registers nothing": bare, "unreadable config": unreadable} {
		if src, ok := got[id.String()]; !ok || !src.Held {
			t.Fatalf("%s: loaded %v, %+v; want it held", name, ok, src)
		}
	}

	if err := s.Unregistered(ctx, known.String()); err != nil {
		t.Fatal(err)
	}
	if err := s.Failed(ctx, known.String(), "HTTP 502"); err != nil {
		t.Fatal(err)
	}
	if err := s.Unregistered(ctx, known.String()); err != nil {
		t.Fatal(err)
	}
	loaded, err = s.Load(ctx)
	if err != nil {
		t.Fatal(err)
	}
	for _, src := range loaded {
		if src.ID == known.String() && (src.RegisteredURL != "" || src.PollError != "HTTP 502") {
			t.Fatalf("after unregistering = %+v; want the URL cleared and the poll error kept", src)
		}
	}
}
