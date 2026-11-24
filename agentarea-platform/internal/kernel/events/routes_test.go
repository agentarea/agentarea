package events

import (
	"slices"
	"strings"
	"testing"
)

func TestRoutesForDLQ(t *testing.T) {
	routes := ConfiguredRoutes(3)
	if len(routes) != 4+2*3 {
		t.Fatalf("%d routes", len(routes))
	}
	router, err := RoutesForDLQ(routes, "streams.events.router.dlq")
	if err != nil {
		t.Fatal(err)
	}
	var streams []string
	for _, r := range router {
		streams = append(streams, r.Stream)
	}
	if !slices.Equal(streams, []string{"streams.events.0", "streams.events.1", "streams.events.2"}) {
		t.Fatalf("router partitions %v", streams)
	}
	one, err := RoutesForDLQ(routes, "tasks.events.trigger-outcomes.dlq")
	if err != nil || len(one) != 1 || one[0].Stream != TaskEvents || one[0].Group != TriggerOutcomeGroup {
		t.Fatalf("%v %v", one, err)
	}
	if _, err := RoutesForDLQ(routes, "nope.dlq"); err == nil || !strings.Contains(err.Error(), "streams.ingest.ingest.dlq") {
		t.Fatalf("unknown dlq: %v", err)
	}
}
