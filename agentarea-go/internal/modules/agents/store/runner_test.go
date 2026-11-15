package store

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestRecordRunnerHelloKeepsAChosenDefault(t *testing.T) {
	ctx := context.Background()
	_, s, other := session(t)
	var c Clients
	id := uuid.New()
	if err := c.Insert(ctx, s, id, "u", "Laptop", nil, "codex", time.Now()); err != nil {
		t.Fatal(err)
	}
	first, second := "gpt-5", "gpt-5.5"
	if ok, err := c.RecordRunnerHello(ctx, other, id, true, []byte(`[]`), &first, time.Now()); err != nil || ok {
		t.Fatalf("another workspace wrote the hello: %v %v", ok, err)
	}
	models := []byte(`[{"name":"gpt-5","reasoning_levels":["low"],"default_reasoning":null}]`)
	if ok, err := c.RecordRunnerHello(ctx, s, id, true, models, &first, time.Now()); err != nil || !ok {
		t.Fatalf("hello: %v %v", ok, err)
	}
	if ok, err := c.RecordRunnerHello(ctx, s, id, false, nil, &second, time.Now()); err != nil || !ok {
		t.Fatalf("second hello: %v %v", ok, err)
	}
	row, ok, err := c.Get(ctx, s, id)
	if err != nil || !ok {
		t.Fatal(ok, err)
	}
	if row.DefaultModel == nil || *row.DefaultModel != first {
		t.Fatalf("default model: %v", row.DefaultModel)
	}
	if string(row.Models) == "" || string(row.Models) == "null" {
		t.Fatalf("models were dropped by a hello without them: %s", row.Models)
	}
}
