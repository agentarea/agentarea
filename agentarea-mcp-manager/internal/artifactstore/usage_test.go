package artifactstore

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/usage"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
)

type versionedUsageS3 struct {
	*fakeS3Client
	pages []*s3.ListObjectVersionsOutput
	err   error
	calls int
}

func (f *versionedUsageS3) ListObjectVersions(_ context.Context, input *s3.ListObjectVersionsInput, _ ...func(*s3.Options)) (*s3.ListObjectVersionsOutput, error) {
	if f.err != nil && f.calls == len(f.pages) {
		return nil, f.err
	}
	page := f.pages[f.calls]
	f.calls++
	return page, nil
}

func TestStorageInventoryCountsNoncurrentVersionsSeparatelyFromVisibleObjects(t *testing.T) {
	prefix := "root/workspaces/ws-a/tasks/task-a/"
	artifactKey := prefix + "artifacts/art_" + strings.Repeat("a", 32) + "/report.txt"
	client := &versionedUsageS3{fakeS3Client: &fakeS3Client{}, pages: []*s3.ListObjectVersionsOutput{
		{Versions: []types.ObjectVersion{
			{Key: aws.String(artifactKey), Size: aws.Int64(13), IsLatest: aws.Bool(true)},
			{Key: aws.String(artifactKey), Size: aws.Int64(7), IsLatest: aws.Bool(false)},
			{Key: aws.String(prefix + "objects/old"), Size: aws.Int64(19), IsLatest: aws.Bool(false)},
		}, IsTruncated: aws.Bool(true), NextKeyMarker: aws.String("next"), NextVersionIdMarker: aws.String("v2")},
		{Versions: []types.ObjectVersion{
			{Key: aws.String(prefix + "current.json"), Size: aws.Int64(11), IsLatest: aws.Bool(true)},
			{Key: aws.String("outside/workspaces/ws-a/tasks/task-a/objects/unowned"), Size: aws.Int64(9999), IsLatest: aws.Bool(true)},
			{Key: aws.String("root/workspaces/ws-b/tasks/task-b/objects/content"), Size: aws.Int64(9007199254740993), IsLatest: aws.Bool(true)},
		}, DeleteMarkers: []types.DeleteMarkerEntry{{Key: aws.String(prefix + "objects/old"), IsLatest: aws.Bool(true)}}},
	}}
	repository := &Repository{cfg: Config{Bucket: "usage", Prefix: "root"}, client: client}
	inventory, err := repository.InventoryStorage(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	observations := make(map[usage.StorageScope]StorageObservation)
	for _, observation := range inventory.Observations {
		observations[observation.StorageScope] = observation
	}
	artifact := observations[usage.StorageScope{WorkspaceID: "ws-a", TaskID: "task-a", ResourceKind: "artifact_storage"}]
	if artifact.CurrentBytes != 13 || artifact.RetainedBytes != 20 || artifact.RetainedVersions != 2 || artifact.CurrentObjects != 1 {
		t.Fatalf("retained artifact usage = %+v", artifact)
	}
	objects := observations[usage.StorageScope{WorkspaceID: "ws-a", TaskID: "task-a", ResourceKind: "workspace_storage"}]
	if objects.CurrentBytes != 0 || objects.RetainedBytes != 19 || objects.DeleteMarkers != 1 {
		t.Fatalf("deleted current key must retain older version: %+v", objects)
	}
	other := observations[usage.StorageScope{WorkspaceID: "ws-b", TaskID: "task-b", ResourceKind: "workspace_storage"}]
	if other.RetainedBytes != 9007199254740993 {
		t.Fatalf("byte precision lost: %d", other.RetainedBytes)
	}
	metadata := observations[usage.StorageScope{WorkspaceID: "ws-a", TaskID: "task-a", ResourceKind: "workspace_metadata"}]
	if metadata.CurrentBytes != 11 {
		t.Fatalf("metadata mixed with content: %+v", metadata)
	}
}

func TestStorageInventoryRejectsIncompleteScan(t *testing.T) {
	client := &versionedUsageS3{fakeS3Client: &fakeS3Client{}, pages: []*s3.ListObjectVersionsOutput{
		{Versions: []types.ObjectVersion{{Key: aws.String("workspaces/ws/tasks/task/objects/a"), Size: aws.Int64(4), IsLatest: aws.Bool(true)}}, IsTruncated: aws.Bool(true), NextKeyMarker: aws.String("next")},
	}, err: errors.New("object store unavailable")}
	repository := &Repository{cfg: Config{Bucket: "usage"}, client: client}
	inventory, err := repository.InventoryStorage(context.Background())
	if err == nil || len(inventory.Observations) != 0 {
		t.Fatalf("partial scan returned as usable inventory: %+v, %v", inventory, err)
	}
}

type artifactUsageRecorder struct {
	events []usage.Event
	err    error
}

func (r *artifactUsageRecorder) Record(_ context.Context, event usage.Event) error {
	r.events = append(r.events, event)
	return r.err
}

func TestArtifactPublicationRetriesKeepStorageIdentityAndSurfacePersistenceFailure(t *testing.T) {
	storedAt := time.Date(2026, 9, 18, 12, 0, 0, 0, time.UTC)
	client := &fakeS3Client{head: &s3.HeadObjectOutput{ContentLength: aws.Int64(7), LastModified: &storedAt, ETag: aws.String("etag"), VersionId: aws.String("version-1")}}
	recorder := &artifactUsageRecorder{err: errors.New("usage store unavailable")}
	repository := &Repository{cfg: Config{Bucket: "usage"}, client: client, recorder: recorder}
	artifact := Artifact{ID: "artifact", Size: 7, objectKey: "workspaces/ws/tasks/task/artifacts/opaque/private-name.txt"}
	if err := repository.recordPublication(context.Background(), "ws", "task", artifact); err == nil {
		t.Fatal("persistence failure was hidden")
	}
	recorder.err = nil
	if err := repository.recordPublication(context.Background(), "ws", "task", artifact); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(recorder.events[0], recorder.events[1]) {
		t.Fatal("retry changed immutable event identity/content")
	}
	encoded, err := json.Marshal(recorder.events[1])
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(encoded), "private-name") {
		t.Fatal("usage leaked artifact file name")
	}
}
