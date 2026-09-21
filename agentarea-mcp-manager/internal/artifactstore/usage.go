package artifactstore

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"path"
	"sort"
	"strings"
	"time"

	"github.com/agentarea/mcp-manager/internal/usage"
	"github.com/agentarea/mcp-manager/internal/workspace"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

// SetUsageRecorder is called during composition, before serving requests.
func (r *Repository) SetUsageRecorder(recorder usage.Recorder) { r.recorder = recorder }

func (r *Repository) StorageNamespaceID() string {
	return usage.StorageNamespaceID(r.cfg.Bucket, r.cfg.Prefix)
}

func (r *Repository) recordPublication(ctx context.Context, workspaceID, taskID string, artifact Artifact) error {
	if r.recorder == nil {
		return nil
	}
	head, err := r.client.HeadObject(ctx, &s3.HeadObjectInput{Bucket: aws.String(r.cfg.Bucket), Key: aws.String(artifact.objectKey)})
	if err != nil {
		return fmt.Errorf("read published artifact usage: %w", err)
	}
	if head.LastModified == nil || aws.ToInt64(head.ContentLength) != artifact.Size {
		return fmt.Errorf("published artifact has no trustworthy storage size or timestamp")
	}
	objectID := storageObjectID(r.cfg.Bucket, artifact.objectKey)
	version := aws.ToString(head.VersionId)
	etag := aws.ToString(head.ETag)
	occurredAt := head.LastModified.UTC()
	identity := sha256.Sum256([]byte(objectID + "\x00" + version + "\x00" + etag + "\x00" + occurredAt.Format(time.RFC3339Nano)))
	data, err := json.Marshal(map[string]any{
		"size_bytes": artifact.Size, "version_id": version, "etag": etag,
		"measurement_status": "observed", "basis": "retained_object",
		"storage_namespace": r.StorageNamespaceID(),
	})
	if err != nil {
		return err
	}
	if err := r.recorder.Record(ctx, usage.Event{
		SchemaVersion: usage.SchemaVersion,
		ID:            hex.EncodeToString(identity[:]), Source: "artifact-store", Kind: "storage.artifact.published",
		WorkspaceID: workspaceID, TaskID: taskID, ResourceKind: "artifact_storage", ResourceID: objectID,
		IncarnationID: version, OccurredAt: occurredAt, Data: data,
	}); err != nil {
		return fmt.Errorf("persist published artifact usage: %w", err)
	}
	return nil
}

type StorageObservation struct {
	usage.StorageScope
	CurrentBytes         int64 `json:"current_bytes"`
	RetainedBytes        int64 `json:"retained_bytes"`
	CurrentObjects       int64 `json:"current_objects"`
	RetainedVersions     int64 `json:"retained_versions"`
	DeleteMarkers        int64 `json:"delete_markers"`
	DeleteMarkerKeyBytes int64 `json:"delete_marker_key_bytes"`
}

type StorageInventory struct {
	StartedAt    time.Time
	CompletedAt  time.Time
	Observations []StorageObservation
}

type versionLister interface {
	ListObjectVersions(context.Context, *s3.ListObjectVersionsInput, ...func(*s3.Options)) (*s3.ListObjectVersionsOutput, error)
}

// InventoryStorage includes noncurrent versions, even when the current key is a
// delete marker. No partial scan is returned as a complete storage observation.
func (r *Repository) InventoryStorage(ctx context.Context) (StorageInventory, error) {
	client, ok := r.client.(versionLister)
	if !ok {
		return StorageInventory{}, fmt.Errorf("storage provider does not expose retained object versions")
	}
	inventory := StorageInventory{StartedAt: time.Now().UTC()}
	prefix := path.Join(r.cfg.Prefix, "workspaces") + "/"
	groups := make(map[usage.StorageScope]*StorageObservation)
	var keyMarker, versionMarker *string
	for {
		page, err := client.ListObjectVersions(ctx, &s3.ListObjectVersionsInput{
			Bucket: aws.String(r.cfg.Bucket), Prefix: aws.String(prefix), MaxKeys: aws.Int32(1000),
			KeyMarker: keyMarker, VersionIdMarker: versionMarker,
		})
		if err != nil {
			return StorageInventory{}, fmt.Errorf("inventory retained storage versions: %w", err)
		}
		get := func(key string) *StorageObservation {
			scope, valid := parseStorageScope(prefix, key)
			if !valid {
				return nil
			}
			if groups[scope] == nil {
				groups[scope] = &StorageObservation{StorageScope: scope}
			}
			return groups[scope]
		}
		for _, version := range page.Versions {
			observation := get(aws.ToString(version.Key))
			if observation == nil {
				continue
			}
			size := aws.ToInt64(version.Size)
			if size < 0 || version.Size == nil {
				return StorageInventory{}, fmt.Errorf("storage provider returned an invalid object size")
			}
			if observation.RetainedBytes > int64(^uint64(0)>>1)-size {
				return StorageInventory{}, fmt.Errorf("retained storage byte count exceeds int64")
			}
			observation.RetainedBytes += size
			observation.RetainedVersions++
			if aws.ToBool(version.IsLatest) {
				observation.CurrentBytes += size
				observation.CurrentObjects++
			}
		}
		for _, marker := range page.DeleteMarkers {
			if observation := get(aws.ToString(marker.Key)); observation != nil {
				observation.DeleteMarkers++
				observation.DeleteMarkerKeyBytes += int64(len(aws.ToString(marker.Key)))
			}
		}
		if !aws.ToBool(page.IsTruncated) {
			break
		}
		if page.NextKeyMarker == nil || (aws.ToString(page.NextKeyMarker) == aws.ToString(keyMarker) && aws.ToString(page.NextVersionIdMarker) == aws.ToString(versionMarker)) {
			return StorageInventory{}, fmt.Errorf("storage version inventory did not advance its cursor")
		}
		keyMarker, versionMarker = page.NextKeyMarker, page.NextVersionIdMarker
	}
	inventory.CompletedAt = time.Now().UTC()
	for _, observation := range groups {
		inventory.Observations = append(inventory.Observations, *observation)
	}
	sort.Slice(inventory.Observations, func(i, j int) bool {
		a, b := inventory.Observations[i], inventory.Observations[j]
		if a.WorkspaceID != b.WorkspaceID {
			return a.WorkspaceID < b.WorkspaceID
		}
		if a.TaskID != b.TaskID {
			return a.TaskID < b.TaskID
		}
		return a.ResourceKind < b.ResourceKind
	})
	return inventory, nil
}

func parseStorageScope(prefix, key string) (usage.StorageScope, bool) {
	if !strings.HasPrefix(key, prefix) {
		return usage.StorageScope{}, false
	}
	parts := strings.Split(strings.TrimPrefix(key, prefix), "/")
	if len(parts) < 4 || parts[1] != "tasks" || parts[3] == "" ||
		workspace.ValidateIdentifier("workspace_id", parts[0]) != nil || workspace.ValidateIdentifier("task_id", parts[2]) != nil {
		return usage.StorageScope{}, false
	}
	kind := "workspace_metadata"
	switch parts[3] {
	case "objects":
		kind = "workspace_storage"
	case "artifacts":
		if len(parts) >= 6 && artifactIDPattern.MatchString(parts[4]) {
			kind = "artifact_storage"
		}
	}
	return usage.StorageScope{WorkspaceID: parts[0], TaskID: parts[2], ResourceKind: kind}, true
}

func storageObjectID(bucket, key string) string {
	hash := sha256.Sum256([]byte(bucket + "\x00" + key))
	return hex.EncodeToString(hash[:])
}
