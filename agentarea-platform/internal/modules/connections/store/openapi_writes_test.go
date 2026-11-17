package store

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
)

func TestOpenAPIWrites(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := workspace(t, pool), workspace(t, pool)
	o := OpenAPI{}
	id := uuid.New()
	now := time.Now().UTC().Truncate(time.Microsecond)
	plain := "application/json"
	q := "json"
	spec := json.RawMessage(`{"openapi":"3.0.0","paths":{"/b":{},"/a":{}}}`)
	created, err := o.Insert(ctx, s, ConnectionNew{
		ID: id, CreatedBy: "u1", Name: "pets", Description: ptr("d"), SpecURL: ptr("https://x/spec.json"),
		SpecContent: spec, BaseURL: "https://api.example.test/{tenant}",
		CustomHeaders: []domain.Header{{Name: "Authorization", Secret: true}, {Name: "Accept", Value: &plain}},
		CustomQuery:   []domain.QueryParam{{Name: "key", Secret: true}, {Name: "fmt", Value: &q}},
		URLVariables:  []string{"tenant"}, AvailableTools: json.RawMessage(`[{"name":"getPet","description":"g","inputSchema":{"type":"object"}}]`),
		Status: "active", Now: now,
	})
	if err != nil {
		t.Fatal(err)
	}
	if created.ID != id.String() || created.CustomHeaders[0].Value != nil || *created.CustomHeaders[1].Value != plain ||
		len(created.AvailableTools) != 1 || created.URLVariables[0] != "tenant" {
		t.Fatalf("created = %+v", created)
	}
	full, ok, err := o.Full(ctx, s, id)
	if err != nil || !ok {
		t.Fatalf("full: %v %v", ok, err)
	}
	doc, isObj := full.SpecContent.(wirejson.Object)
	if !isObj {
		t.Fatalf("spec = %T", full.SpecContent)
	}
	paths, _ := doc.Get("paths")
	if p := paths.(wirejson.Object); p[0].Key != "/a" || p[1].Key != "/b" {
		t.Fatalf("spec paths keep jsonb order: %v", p)
	}
	if _, ok, _ := o.Full(ctx, other, id); ok {
		t.Fatal("another workspace reads the row")
	}
	if _, ok, _ := o.Lock(ctx, other, id); ok {
		t.Fatal("another workspace locks the row")
	}

	saved, err := o.Save(ctx, s, id, ConnectionRow{Name: "renamed", BaseURL: "https://api.example.test", Cost: map[string]any{"model": "free"},
		AvailableTools: json.RawMessage(`[]`), Now: now.Add(time.Second)})
	if err != nil || !saved {
		t.Fatalf("save: %v %v", saved, err)
	}
	if saved, _ := o.Save(ctx, other, id, ConnectionRow{Name: "x", AvailableTools: json.RawMessage(`[]`), Now: now}); saved {
		t.Fatal("another workspace saved the row")
	}
	got, _, err := o.Lock(ctx, s, id)
	if err != nil || got.Name != "renamed" || got.CustomHeaders != nil || got.SpecContent != nil || got.Cost["model"] != "free" {
		t.Fatalf("after save = %+v, %v", got, err)
	}

	if ok, err := o.SetDiscovery(ctx, s, id, json.RawMessage(`[{"name":"a","description":"","inputSchema":null}]`), spec, now); err != nil || !ok {
		t.Fatalf("discovery: %v %v", ok, err)
	}
	if ok, err := o.SetLastDispatch(ctx, s, id, map[string]any{"status": "succeeded", "at": "2026-11-12T10:00:00+00:00", "error": nil}); err != nil || !ok {
		t.Fatalf("dispatch: %v %v", ok, err)
	}
	if ok, _ := o.SetLastDispatch(ctx, other, id, map[string]any{"status": "x"}); ok {
		t.Fatal("another workspace stamped the row")
	}
	got, _, _ = o.Full(ctx, s, id)
	if len(got.AvailableTools) != 1 || got.AvailableTools[0].Name != "a" || got.LastDispatch["status"] != "succeeded" || got.SpecContent == nil {
		t.Fatalf("after discovery = %+v", got)
	}
}
