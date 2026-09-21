package usage

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestStorageZeroSerializesWithUncommittedPublication(t *testing.T) {
	store := openTestStore(t)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	namespace := StorageNamespaceID(uuid.NewString(), "")
	publication := testEvent()
	publication.Source = "artifact-store"
	publication.Kind = "storage.artifact.published"
	publication.TaskID = uuid.NewString()
	publication.ResourceKind = "artifact_storage"
	publication.Data = json.RawMessage(fmt.Sprintf(`{"storage_namespace":%q,"size_bytes":42}`, namespace))
	if err := store.Record(ctx, publication); err != nil {
		t.Fatal(err)
	}
	scope := StorageScope{WorkspaceID: publication.WorkspaceID, TaskID: publication.TaskID, ResourceKind: publication.ResourceKind}
	before, err := store.KnownStorageScopes(ctx, namespace)
	if err != nil {
		t.Fatal(err)
	}

	// A publication has inserted its fact but has not yet committed. The zero
	// writer must wait, then compare against the newly committed scope version.
	tx, err := store.db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback() }()
	publication.ID = uuid.NewString()
	publication.ResourceID = uuid.NewString()
	if err := RecordTx(ctx, tx, publication); err != nil {
		t.Fatal(err)
	}

	// A different task in the same namespace must remain independently writable.
	other := publication
	other.ID = uuid.NewString()
	other.TaskID = uuid.NewString()
	otherCtx, cancelOther := context.WithTimeout(ctx, time.Second)
	err = store.Record(otherCtx, other)
	cancelOther()
	if err != nil {
		t.Fatalf("unrelated storage scope blocked: %v", err)
	}

	zero := publication
	zero.ID = uuid.NewString()
	zero.Source = "storage-inventory"
	zero.Kind = "storage.sample"
	zero.Data = json.RawMessage(fmt.Sprintf(`{"storage_namespace":%q,"current_bytes":0,"retained_bytes":0,"current_objects":0,"retained_versions":0,"delete_markers":0,"delete_marker_key_bytes":0}`, namespace))
	blockedCtx, cancelBlocked := context.WithTimeout(ctx, 100*time.Millisecond)
	err = store.RecordStorageZero(blockedCtx, zero, before[scope])
	if err == nil || blockedCtx.Err() != context.DeadlineExceeded {
		cancelBlocked()
		t.Fatalf("zero did not wait for uncommitted publication: %v", err)
	}
	cancelBlocked()
	if err := tx.Commit(); err != nil {
		t.Fatal(err)
	}
	if err := store.RecordStorageZero(ctx, zero, before[scope]); err != nil {
		t.Fatal(err)
	}
	var zeroCount int
	if err := store.db.QueryRowContext(ctx, `SELECT count(*) FROM resource_usage_events
		WHERE source='storage-inventory' AND workspace_id=$1 AND task_id=$2`, scope.WorkspaceID, scope.TaskID).Scan(&zeroCount); err != nil {
		t.Fatal(err)
	}
	if zeroCount != 0 {
		t.Fatalf("stale inventory closed a concurrently published scope: %d zeros", zeroCount)
	}

	after, err := store.KnownStorageScopes(ctx, namespace)
	if err != nil {
		t.Fatal(err)
	}
	if after[scope] <= before[scope] {
		t.Fatalf("committed publication did not remain active: before=%v after=%v", before, after)
	}
	if err := store.RecordStorageZero(ctx, zero, after[scope]); err != nil {
		t.Fatal(err)
	}
	// Two collectors using the same snapshot may close the scope only once.
	zero.ID = uuid.NewString()
	if err := store.RecordStorageZero(ctx, zero, after[scope]); err != nil {
		t.Fatal(err)
	}
	if err := store.db.QueryRowContext(ctx, `SELECT count(*) FROM resource_usage_events
		WHERE source='storage-inventory' AND workspace_id=$1 AND task_id=$2`, scope.WorkspaceID, scope.TaskID).Scan(&zeroCount); err != nil {
		t.Fatal(err)
	}
	if zeroCount != 1 {
		t.Fatalf("later empty observation did not close exactly once: %d zeros", zeroCount)
	}
	after, err = store.KnownStorageScopes(ctx, namespace)
	if err != nil {
		t.Fatal(err)
	}
	if _, active := after[scope]; active {
		t.Fatal("scope remains active after its later empty observation")
	}
}
