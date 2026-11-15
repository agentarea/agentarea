package store

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestCollectionUpdateTellsAbsentFromNull(t *testing.T) {
	ctx := context.Background()
	_, s, _ := session(t)
	id, desc, name := uuid.New(), "kept", "Renamed"
	var c Collections
	if err := c.Insert(ctx, s, id, "u", "Docs", "docs", &desc, time.Now()); err != nil {
		t.Fatal(err)
	}
	if err := c.Update(ctx, s, id, &name, false, nil, time.Now()); err != nil {
		t.Fatal(err)
	}
	got, _, _ := c.Get(ctx, s, id)
	if got.Name != "Renamed" || got.Description == nil || *got.Description != "kept" {
		t.Fatalf("absent description changed: %+v", got)
	}
	if err := c.Update(ctx, s, id, nil, true, nil, time.Now()); err != nil {
		t.Fatal(err)
	}
	if got, _, _ = c.Get(ctx, s, id); got.Description != nil {
		t.Fatalf("null description not cleared: %+v", got)
	}
}
