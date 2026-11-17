package events

import (
	"fmt"
	"slices"
	"strings"
)

// GroupRoute is a consumer group the platform runs on a stream, and where its failures go
// (broker/routes.py ConsumerGroupRoute).
type GroupRoute struct {
	Stream string
	Group  string
	DLQ    string
}

// ConfiguredRoutes are ingest, delivery, the platform stream, trigger outcomes, then each
// stream-events partition per group (configured_routes).
func ConfiguredRoutes(partitions int) []GroupRoute {
	routes := []GroupRoute{
		{StreamsIngest, IngestGroup, DeadLetterTopic(StreamsIngest, IngestGroup)},
		{TaskEvents, DeliveryGroup, DeadLetterTopic(TaskEvents, DeliveryGroup)},
		{TaskEvents, PlatformGroup, DeadLetterTopic(TaskEvents, PlatformGroup)},
		{TaskEvents, TriggerOutcomeGroup, DeadLetterTopic(TaskEvents, TriggerOutcomeGroup)},
	}
	for _, g := range []string{RouterGroup, EventsViewGroup} {
		for _, p := range StreamEventsPartitions(partitions) {
			routes = append(routes, GroupRoute{p, g, DeadLetterTopic(StreamEvents, g)})
		}
	}
	return routes
}

// RoutesForDLQ are the routes that dead-letter into dlq: one, or one per partition of a
// partitioned topic (routes_for_dlq).
func RoutesForDLQ(routes []GroupRoute, dlq string) ([]GroupRoute, error) {
	var found []GroupRoute
	known := map[string]struct{}{}
	for _, r := range routes {
		known[r.DLQ] = struct{}{}
		if r.DLQ == dlq {
			found = append(found, r)
		}
	}
	if len(found) == 0 {
		names := make([]string, 0, len(known))
		for n := range known {
			names = append(names, n)
		}
		slices.Sort(names)
		return nil, fmt.Errorf("%s is not a configured dead-letter stream (known: %s)", dlq, strings.Join(names, ", "))
	}
	return found, nil
}
