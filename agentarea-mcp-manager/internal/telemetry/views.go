package telemetry

import (
	"go.opentelemetry.io/otel/attribute"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
)

// Instruments this service exports (ADR-0048 §9).
const (
	ProcessUptime           = "agentarea.process.uptime"
	MCPColdStartDuration    = "agentarea.mcp.cold_start.duration"
	MCPColdStarts           = "agentarea.mcp.cold_starts"
	MCPGatewayDuration      = "agentarea.mcp.gateway.request.duration"
	MCPGatewayRequests      = "agentarea.mcp.gateway.requests"
	MCPGatewayInFlight      = "agentarea.mcp.gateway.in_flight"
	MCPGatewayOldest        = "agentarea.mcp.gateway.oldest_in_flight"
	MCPInstances            = "agentarea.mcp.instances"
	MCPIdleReaps            = "agentarea.mcp.idle_reaps"
	MCPUpstreamResponses    = "agentarea.mcp.upstream.responses"
	httpServerDuration      = "http.server.request.duration"
	httpServerRequestBytes  = "http.server.request.body.size"
	httpServerResponseBytes = "http.server.response.body.size"
)

// Attribute keys; every value is a closed set declared in code. Instance,
// workspace and spec identities are never attributes: Postgres, logs and
// traces carry them.
const (
	AttrPhase     = attribute.Key("phase")
	AttrOutcome   = attribute.Key("outcome")
	AttrReason    = attribute.Key("reason")
	AttrPlane     = attribute.Key("plane")
	AttrStatus    = attribute.Key("status")
	AttrCold      = attribute.Key("cold")
	AttrState     = attribute.Key("state")
	AttrMCPMethod = attribute.Key("mcp.method.name")
)

var (
	coldStartBuckets = []float64{1, 2, 5, 8, 10, 15, 20, 30, 45, 60, 120, 300}
	// A gateway request spans a cold start and the tool call behind it.
	gatewayBuckets    = []float64{0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 900, 1800}
	httpServerBuckets = []float64{0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30}
)

// view is one exported instrument's allowed attribute keys and, for a
// histogram, its buckets. The SDK drops every key that is not listed.
type view struct {
	instrument string
	keys       []attribute.Key
	buckets    []float64
	drop       bool
}

var views = []view{
	{instrument: MCPColdStartDuration, keys: []attribute.Key{AttrPhase, AttrOutcome, AttrPlane}, buckets: coldStartBuckets},
	{instrument: MCPColdStarts, keys: []attribute.Key{AttrOutcome, AttrReason, AttrPlane}},
	{instrument: MCPGatewayDuration, keys: []attribute.Key{AttrMCPMethod, AttrStatus, AttrCold}, buckets: gatewayBuckets},
	{instrument: MCPGatewayRequests, keys: []attribute.Key{AttrMCPMethod, AttrStatus, AttrCold}},
	{instrument: MCPGatewayInFlight},
	{instrument: MCPGatewayOldest},
	{instrument: MCPInstances, keys: []attribute.Key{AttrState}},
	{instrument: MCPIdleReaps},
	{instrument: MCPUpstreamResponses, keys: []attribute.Key{AttrStatus}},
	{instrument: ProcessUptime},
	{
		instrument: httpServerDuration,
		keys:       []attribute.Key{"http.request.method", "http.route", "http.response.status_code", "error.type"},
		buckets:    httpServerBuckets,
	},
	{instrument: httpServerRequestBytes, drop: true},
	{instrument: httpServerResponseBytes, drop: true},
}

func sdkViews() []sdkmetric.View {
	out := make([]sdkmetric.View, 0, len(views))
	for _, v := range views {
		stream := sdkmetric.Stream{AttributeFilter: attribute.NewAllowKeysFilter(v.keys...)}
		switch {
		case v.drop:
			stream.Aggregation = sdkmetric.AggregationDrop{}
		case v.buckets != nil:
			stream.Aggregation = sdkmetric.AggregationExplicitBucketHistogram{Boundaries: v.buckets}
		}
		out = append(out, sdkmetric.NewView(sdkmetric.Instrument{Name: v.instrument}, stream))
	}
	return out
}
