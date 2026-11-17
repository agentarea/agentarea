package artifactstore

import (
	"context"
	"fmt"
	"path"
	"sort"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"

	usage "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/resourceusage"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/workspace"
)

type versionLister interface {
	ListObjectVersions(context.Context, *s3.ListObjectVersionsInput, ...func(*s3.Options)) (*s3.ListObjectVersionsOutput, error)
}

// Location is the bucket and key prefix the repository stores under.
func (r *Repository) Location() (bucket, prefix string) { return r.cfg.Bucket, r.cfg.Prefix }

// Inventory includes noncurrent versions, even when the current key is a
// delete marker. No partial scan is returned as a complete storage observation.
func (s *Repository) Inventory(ctx context.Context) (usage.StorageInventory, error) {
	client, ok := s.client.(versionLister)
	if !ok {
		return usage.StorageInventory{}, fmt.Errorf("storage provider does not expose retained object versions")
	}
	inventory := usage.StorageInventory{StartedAt: time.Now().UTC()}
	prefix := path.Join(s.cfg.Prefix, "workspaces") + "/"
	groups := make(map[usage.StorageScope]*usage.StorageObservation)
	var keyMarker, versionMarker *string
	for {
		page, err := client.ListObjectVersions(ctx, &s3.ListObjectVersionsInput{
			Bucket: aws.String(s.cfg.Bucket), Prefix: aws.String(prefix), MaxKeys: aws.Int32(1000),
			KeyMarker: keyMarker, VersionIdMarker: versionMarker,
		})
		if err != nil {
			return usage.StorageInventory{}, fmt.Errorf("inventory retained storage versions: %w", err)
		}
		get := func(key string) *usage.StorageObservation {
			scope, valid := parseStorageScope(prefix, key)
			if !valid {
				return nil
			}
			if groups[scope] == nil {
				groups[scope] = &usage.StorageObservation{StorageScope: scope}
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
				return usage.StorageInventory{}, fmt.Errorf("storage provider returned an invalid object size")
			}
			if observation.RetainedBytes > int64(^uint64(0)>>1)-size {
				return usage.StorageInventory{}, fmt.Errorf("retained storage byte count exceeds int64")
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
			return usage.StorageInventory{}, fmt.Errorf("storage version inventory did not advance its cursor")
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
		if len(parts) >= 6 && IsArtifactID(parts[4]) {
			kind = "artifact_storage"
		}
	}
	return usage.StorageScope{WorkspaceID: parts[0], TaskID: parts[2], ResourceKind: kind}, true
}
