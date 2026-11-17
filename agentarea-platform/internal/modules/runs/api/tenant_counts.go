package api

import (
	"context"
	"time"
)

// Windows are the cut-offs runs are counted from: a day, a week and 30 days ago.
type Windows struct {
	Day, Week, Month time.Time
}

// TenantCounts are runs' counts over every tenant workspace. A workspace or user is active in a
// window when it created a run in it. Status, origin and failure reason are the stored values.
type TenantCounts struct {
	ActiveWorkspaces7d, ActiveWorkspaces30d int
	ActiveUsers7d, ActiveUsers30d           int
	ByStatus, ByOrigin, FailedByReason      map[string]int
	// MedianDurationSeconds is nil when no run completed in the last day.
	MedianDurationSeconds *float64
	// FirstCompleted is when each of the given workspaces first completed a run; a workspace
	// without one is absent.
	FirstCompleted map[string]time.Time
}

// TenantCounter is analytics/pulse_repository.py's _active, runs_24h, _median_duration and _activation's succeeded_within.
type TenantCounter interface {
	TenantCounts(ctx context.Context, w Windows, workspaces []string) (TenantCounts, error)
}
