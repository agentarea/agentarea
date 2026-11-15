package app

import (
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams"
)

// streamEventDedupTTL is the stream-event dedup cache's TTL (DedupCache's default).
const streamEventDedupTTL = 24 * time.Hour

// eventsMissing names the streams ports the router fires through that have no implementation:
// without them every trigger firing would fail and be dead-lettered.
func eventsMissing(d streams.Deps) []string {
	var missing []string
	if d.Tasks == nil {
		missing = append(missing, "streams Tasks (runs task creation)")
	}
	if d.FiringTasks == nil {
		missing = append(missing, "streams FiringTasks (runs task reads)")
	}
	if d.Processors == nil {
		missing = append(missing, "sandbox processor runner (sandbox)")
	}
	return missing
}
