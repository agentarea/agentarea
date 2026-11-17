package resourceusage

import "time"

// StorageScope is one task's content of one kind.
type StorageScope struct {
	WorkspaceID  string `json:"workspace_id"`
	TaskID       string `json:"task_id"`
	ResourceKind string `json:"resource_kind"`
}

// StorageObservation is what a scope retains: current objects and every
// noncurrent version and delete marker the bucket keeps.
type StorageObservation struct {
	StorageScope
	CurrentBytes         int64 `json:"current_bytes"`
	RetainedBytes        int64 `json:"retained_bytes"`
	CurrentObjects       int64 `json:"current_objects"`
	RetainedVersions     int64 `json:"retained_versions"`
	DeleteMarkers        int64 `json:"delete_markers"`
	DeleteMarkerKeyBytes int64 `json:"delete_marker_key_bytes"`
}

// StorageInventory is one complete scan of the artifact bucket.
type StorageInventory struct {
	StartedAt    time.Time
	CompletedAt  time.Time
	Observations []StorageObservation
}
