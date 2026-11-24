package api

import "context"

// RunnerPresence tells which clients' runners are connected now.
type RunnerPresence interface {
	// Online maps each of clientIDs whose runner is connected to true.
	Online(ctx context.Context, clientIDs []string) (map[string]bool, error)
}
