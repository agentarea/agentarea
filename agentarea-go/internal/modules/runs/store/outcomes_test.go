package store

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestOutcomeTaskIsReadInItsWorkspaceOnly(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := workspace(t, pool), workspace(t, pool)
	var r Runs
	id, trigger := uuid.NewString(), uuid.NewString()
	if err := r.CreateTask(ctx, s, NewTask{
		ID: id, AgentID: uuid.NewString(), Description: "d", Status: "running", CreatedBy: "user-1",
		Parameters: map[string]any{"delivery_address": map[string]any{"type": "slack"}},
		Metadata:   map[string]any{"task_webhook": map[string]any{"url": "https://x.test"}},
		OriginType: "trigger", OriginID: trigger,
	}, time.Now()); err != nil {
		t.Fatal(err)
	}
	row, ok, err := r.OutcomeTaskOf(ctx, s, uuid.MustParse(id))
	if err != nil || !ok {
		t.Fatalf("read = %v %v", ok, err)
	}
	if row.CreatedBy != "user-1" || row.OriginType.String != "trigger" || row.OriginID.String != trigger ||
		row.CorrelationID.String != id || !strings.Contains(string(row.Parameters), "delivery_address") ||
		!strings.Contains(string(row.TaskMetadata), "task_webhook") {
		t.Fatalf("row = %+v", row)
	}
	if _, ok, err := r.OutcomeTaskOf(ctx, other, uuid.MustParse(id)); ok || err != nil {
		t.Fatalf("another workspace read it: %v %v", ok, err)
	}
}
