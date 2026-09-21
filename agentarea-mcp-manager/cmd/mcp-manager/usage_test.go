package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"sync/atomic"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/artifactstore"
	"github.com/agentarea/mcp-manager/internal/usage"
	"github.com/google/uuid"
)

func TestStorageCollectorRecoversDeletedScopesFromDurableFacts(t *testing.T) {
	dsn := os.Getenv("USAGE_TEST_DATABASE_URL")
	if dsn == "" {
		if os.Getenv("USAGE_REQUIRE_DB") == "1" {
			t.Fatal("USAGE_TEST_DATABASE_URL required")
		}
		t.Skip("USAGE_TEST_DATABASE_URL not set")
	}
	t.Setenv("AWS_ACCESS_KEY_ID", "usage-test")
	t.Setenv("AWS_SECRET_ACCESS_KEY", "usage-test")
	workspaceID := uuid.NewString()
	var inventoryKind atomic.Int32
	var unavailable atomic.Bool
	var store *usage.Store
	publicationDuringScan := make(chan usage.Event, 1)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/xml")
		if unavailable.Load() {
			w.WriteHeader(http.StatusForbidden)
			_, _ = w.Write([]byte(`<Error><Code>AccessDenied</Code></Error>`))
			return
		}
		// The inventory snapshot is already empty. Commit a publication before
		// returning that snapshot, without including the newly published object.
		select {
		case event := <-publicationDuringScan:
			if err := store.Record(r.Context(), event); err != nil {
				http.Error(w, err.Error(), http.StatusForbidden)
				return
			}
		default:
		}
		switch inventoryKind.Load() {
		case 1:
			_, _ = fmt.Fprintf(w, `<ListVersionsResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>false</IsTruncated><Version><Key>workspaces/%s/tasks/storage-inventory/objects/empty.txt</Key><VersionId>empty-version</VersionId><IsLatest>true</IsLatest><LastModified>2026-09-18T12:00:00Z</LastModified><Size>0</Size></Version></ListVersionsResult>`, workspaceID)
			return
		case 2:
			_, _ = fmt.Fprintf(w, `<ListVersionsResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>false</IsTruncated><DeleteMarker><Key>workspaces/%s/tasks/storage-inventory/objects/empty.txt</Key><VersionId>delete-version</VersionId><IsLatest>true</IsLatest><LastModified>2026-09-18T12:00:00Z</LastModified></DeleteMarker></ListVersionsResult>`, workspaceID)
			return
		}
		_, _ = w.Write([]byte(`<ListVersionsResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>false</IsTruncated></ListVersionsResult>`))
	}))
	defer server.Close()
	ctx := context.Background()
	repository, err := artifactstore.NewFromConfig(ctx, artifactstore.Config{Bucket: uuid.NewString(), Region: "us-east-1", Endpoint: server.URL, ForcePathStyle: true, MaxBytes: 1024, MaxCount: 10, MaxTotalBytes: 4096})
	if err != nil {
		t.Fatal(err)
	}
	store, err = usage.OpenStore(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	var publication usage.Event
	for _, source := range []string{"artifact-store", "storage-inventory"} {
		kind := "storage.artifact.published"
		resourceKind := "artifact_storage"
		if source == "storage-inventory" {
			kind = "storage.sample"
			resourceKind = "workspace_storage"
		}
		data, err := json.Marshal(map[string]any{"storage_namespace": repository.StorageNamespaceID(), "retained_bytes": 42})
		if err != nil {
			t.Fatal(err)
		}
		event := usage.Event{SchemaVersion: usage.SchemaVersion, ID: uuid.NewString(), Source: source, Kind: kind, WorkspaceID: workspaceID, TaskID: source, ResourceKind: resourceKind, ResourceID: uuid.NewString(), OccurredAt: time.Now().UTC(), Data: data}
		if source == "artifact-store" {
			publication = event
		}
		if err := store.Record(ctx, event); err != nil {
			t.Fatal(err)
		}
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
	// A new collector needs neither a Redis scope set nor an earlier inventory:
	// publication history alone discovers a key removed between scan ticks.
	store, err = usage.OpenStore(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = store.Close() }()
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	assertCounts := func(wantTotal, wantZeros int) {
		t.Helper()
		var total, zeros int
		if err := db.QueryRowContext(ctx, `SELECT count(*), count(*) FILTER (
			WHERE kind='storage.sample' AND data @> '{"current_bytes":0,"retained_bytes":0,"current_objects":0,"retained_versions":0,"delete_markers":0,"delete_marker_key_bytes":0}'::jsonb)
			FROM resource_usage_events WHERE workspace_id=$1 AND data->>'storage_namespace'=$2
			AND kind IN ('storage.sample','storage.artifact.published')
			AND source IN ('storage-inventory','artifact-store')`, workspaceID, repository.StorageNamespaceID()).Scan(&total, &zeros); err != nil {
			t.Fatal(err)
		}
		if total != wantTotal || zeros != wantZeros {
			t.Fatalf("storage events = %d, tombstones = %d; want %d, %d", total, zeros, wantTotal, wantZeros)
		}
	}
	scan := func(wantTotal, wantZeros int) {
		t.Helper()
		if err := collectStorageUsage(ctx, repository, store); err != nil {
			t.Fatal(err)
		}
		assertCounts(wantTotal, wantZeros)
	}
	assertInventory := func(want artifactstore.StorageObservation) {
		t.Helper()
		var data []byte
		if err := db.QueryRowContext(ctx, `SELECT data FROM resource_usage_events
			WHERE workspace_id=$1 AND task_id='storage-inventory' AND resource_kind='workspace_storage'
			AND kind='storage.sample' AND source='storage-inventory' AND data->>'storage_namespace'=$2
			ORDER BY sequence DESC LIMIT 1`, workspaceID, repository.StorageNamespaceID()).Scan(&data); err != nil {
			t.Fatal(err)
		}
		var got artifactstore.StorageObservation
		if err := json.Unmarshal(data, &got); err != nil {
			t.Fatal(err)
		}
		if got != want {
			t.Fatalf("latest inventory = %+v, want %+v", got, want)
		}
		scopes, err := store.KnownStorageScopes(ctx, repository.StorageNamespaceID())
		if err != nil {
			t.Fatal(err)
		}
		if len(scopes) != 1 || scopes[want.StorageScope] == 0 {
			t.Fatalf("active inventory scopes = %+v, want %+v", scopes, want.StorageScope)
		}
	}
	assertCounts(2, 0)
	scan(4, 2)
	scan(4, 2)
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
	store, err = usage.OpenStore(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	scan(4, 2)

	// Re-delivering an immutable publication must not revive a tombstoned scope.
	if err := store.Record(ctx, publication); err != nil {
		t.Fatal(err)
	}
	scan(4, 2)
	publication.ID = uuid.NewString()
	publication.OccurredAt = publication.OccurredAt.Add(-time.Hour)
	if err := store.Record(ctx, publication); err != nil {
		t.Fatal(err)
	}
	assertCounts(5, 2)
	scopes, err := store.KnownStorageScopes(ctx, repository.StorageNamespaceID())
	if err != nil {
		t.Fatal(err)
	}
	if len(scopes) != 1 || scopes[usage.StorageScope{WorkspaceID: workspaceID, TaskID: "artifact-store", ResourceKind: "artifact_storage"}] == 0 {
		t.Fatalf("new publication did not revive its scope: %+v", scopes)
	}
	scan(6, 3)
	scan(6, 3)

	// A real SDK inventory of a zero-byte version is active by object counts.
	inventoryKind.Store(1)
	scan(7, 3)
	inventoryScope := usage.StorageScope{WorkspaceID: workspaceID, TaskID: "storage-inventory", ResourceKind: "workspace_storage"}
	assertInventory(artifactstore.StorageObservation{StorageScope: inventoryScope, CurrentObjects: 1, RetainedVersions: 1})
	unavailable.Store(true)
	if err := collectStorageUsage(ctx, repository, store); err == nil {
		t.Fatal("incomplete inventory accepted")
	}
	assertCounts(7, 3)
	assertInventory(artifactstore.StorageObservation{StorageScope: inventoryScope, CurrentObjects: 1, RetainedVersions: 1})
	unavailable.Store(false)
	inventoryKind.Store(0)
	scan(8, 4)
	scan(8, 4)

	inventoryKind.Store(2)
	scan(9, 4)
	assertInventory(artifactstore.StorageObservation{StorageScope: inventoryScope, DeleteMarkers: 1, DeleteMarkerKeyBytes: int64(len("workspaces/" + workspaceID + "/tasks/storage-inventory/objects/empty.txt"))})
	inventoryKind.Store(0)
	scan(10, 5)
	scan(10, 5)

	latePublication := publication
	latePublication.ID = uuid.NewString()
	latePublication.ResourceID = uuid.NewString()
	latePublication.TaskID = "published-during-scan"
	latePublication.OccurredAt = time.Now().UTC()
	publicationDuringScan <- latePublication
	// A scan cannot close a scope that was first published after it began.
	scan(11, 5)
	scopes, err = store.KnownStorageScopes(ctx, repository.StorageNamespaceID())
	if err != nil {
		t.Fatal(err)
	}
	want := usage.StorageScope{WorkspaceID: workspaceID, TaskID: latePublication.TaskID, ResourceKind: latePublication.ResourceKind}
	if len(scopes) != 1 || scopes[want] == 0 {
		t.Fatalf("publication during inventory was prematurely closed: got %+v, want %+v", scopes, want)
	}
	// If the object disappears before the next scan, that later empty
	// inventory closes its scope exactly once.
	scan(12, 6)
	scan(12, 6)

	// A scope that was already active at scan start needs the same protection.
	activePublication := publication
	activePublication.ID = uuid.NewString()
	activePublication.ResourceID = uuid.NewString()
	activePublication.OccurredAt = time.Now().UTC()
	if err := store.Record(ctx, activePublication); err != nil {
		t.Fatal(err)
	}
	assertCounts(13, 6)
	activePublication.ID = uuid.NewString()
	activePublication.ResourceID = uuid.NewString()
	activePublication.OccurredAt = time.Now().UTC()
	publicationDuringScan <- activePublication
	scan(14, 6)
	scopes, err = store.KnownStorageScopes(ctx, repository.StorageNamespaceID())
	if err != nil {
		t.Fatal(err)
	}
	want = usage.StorageScope{WorkspaceID: workspaceID, TaskID: activePublication.TaskID, ResourceKind: activePublication.ResourceKind}
	if len(scopes) != 1 || scopes[want] == 0 {
		t.Fatalf("concurrent publication to an active scope was closed: got %+v, want %+v", scopes, want)
	}
	scan(15, 7)
	scan(15, 7)

	t.Run("scope isolation and incomplete observations", func(t *testing.T) {
		namespace := uuid.NewString()
		base := usage.StorageScope{WorkspaceID: workspaceID, TaskID: "isolated", ResourceKind: "workspace_storage"}
		otherWorkspace := base
		otherWorkspace.WorkspaceID = uuid.NewString()
		otherTask := base
		otherTask.TaskID = "other-task"
		otherKind := base
		otherKind.ResourceKind = "workspace_metadata"
		record := func(scope usage.StorageScope, namespace string, counters map[string]int64) {
			t.Helper()
			data := map[string]any{"storage_namespace": namespace}
			for key, value := range counters {
				data[key] = value
			}
			payload, err := json.Marshal(data)
			if err != nil {
				t.Fatal(err)
			}
			if err := store.Record(ctx, usage.Event{SchemaVersion: usage.SchemaVersion, ID: uuid.NewString(), Source: "storage-inventory", Kind: "storage.sample", WorkspaceID: scope.WorkspaceID, TaskID: scope.TaskID, ResourceKind: scope.ResourceKind, ResourceID: uuid.NewString(), OccurredAt: time.Now().UTC(), Data: payload}); err != nil {
				t.Fatal(err)
			}
		}
		expected := make(map[usage.StorageScope]bool)
		for _, scope := range []usage.StorageScope{base, otherWorkspace, otherTask, otherKind} {
			record(scope, namespace, map[string]int64{"retained_bytes": 1})
			expected[scope] = true
		}
		fields := []string{"current_bytes", "retained_bytes", "current_objects", "retained_versions", "delete_markers", "delete_marker_key_bytes"}
		zeros := map[string]int64{}
		for _, field := range fields {
			zeros[field] = 0
		}
		record(base, namespace, zeros)
		delete(expected, base)
		// The same scope remains active in a separate storage namespace.
		record(base, namespace+"-other", map[string]int64{"retained_bytes": 1})
		for _, field := range fields {
			for _, missing := range []bool{false, true} {
				scope := base
				scope.TaskID = fmt.Sprintf("%s-missing-%t", field, missing)
				counters := map[string]int64{}
				for key := range zeros {
					counters[key] = 0
				}
				if missing {
					delete(counters, field)
				} else {
					counters[field] = 1
				}
				record(scope, namespace, counters)
				expected[scope] = true
			}
		}
		scopes, err := store.KnownStorageScopes(ctx, namespace)
		if err != nil {
			t.Fatal(err)
		}
		for scope := range scopes {
			if !expected[scope] {
				t.Fatalf("unexpected or duplicate active scope: %+v", scope)
			}
			delete(expected, scope)
		}
		if len(expected) != 0 {
			t.Fatalf("missing active scopes: %+v", expected)
		}
		scopes, err = store.KnownStorageScopes(ctx, namespace+"-other")
		if err != nil {
			t.Fatal(err)
		}
		if len(scopes) != 1 || scopes[base] == 0 {
			t.Fatalf("other namespace active scopes = %+v, want %+v", scopes, base)
		}
	})
}
