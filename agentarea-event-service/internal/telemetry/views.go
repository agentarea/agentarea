package telemetry

import (
	"go.opentelemetry.io/otel/attribute"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
)

// Instruments this service exports (ADR-0048 §9).
const (
	ProcessUptime       = "agentarea.process.uptime"
	EventPolls          = "agentarea.event.polls"
	EventPollDuration   = "agentarea.event.poll.duration"
	EventItemsPublished = "agentarea.event.items_published"
	EventPollers        = "agentarea.event.pollers"
)

// Attribute keys; every value is a closed set declared in code.
const (
	AttrTransport = attribute.Key("transport")
	AttrOutcome   = attribute.Key("outcome")
	AttrState     = attribute.Key("state")
)

var pollBuckets = []float64{0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30}

// view is one exported instrument's allowed attribute keys and, for a
// histogram, its buckets. The SDK drops every key that is not listed.
type view struct {
	instrument string
	keys       []attribute.Key
	buckets    []float64
}

var views = []view{
	{instrument: EventPolls, keys: []attribute.Key{AttrTransport, AttrOutcome}},
	{instrument: EventPollDuration, keys: []attribute.Key{AttrTransport}, buckets: pollBuckets},
	{instrument: EventItemsPublished, keys: []attribute.Key{AttrTransport}},
	{instrument: EventPollers, keys: []attribute.Key{AttrState}},
	{instrument: ProcessUptime},
}

func sdkViews() []sdkmetric.View {
	out := make([]sdkmetric.View, 0, len(views))
	for _, v := range views {
		stream := sdkmetric.Stream{AttributeFilter: attribute.NewAllowKeysFilter(v.keys...)}
		if v.buckets != nil {
			stream.Aggregation = sdkmetric.AggregationExplicitBucketHistogram{Boundaries: v.buckets}
		}
		out = append(out, sdkmetric.NewView(sdkmetric.Instrument{Name: v.instrument}, stream))
	}
	return out
}
