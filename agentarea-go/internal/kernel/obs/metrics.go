package obs

// Instrument names every process exports (ADR-0048). Python's table
// (observability/telemetry.py INSTRUMENTS) and the Go services' (mcp-manager
// and event-service telemetry/views.go) merged: an instrument not listed
// here is dropped, as Python's catch-all View drops it.
const (
	HTTPServerDuration       = "http.server.request.duration"
	HTTPClientDuration       = "http.client.request.duration"
	ProcessUptime            = "agentarea.process.uptime"
	AuthzDuration            = "agentarea.authz.duration"
	BrokerGroupLag           = "agentarea.broker.group.lag"
	BrokerGroupPending       = "agentarea.broker.group.pending"
	BrokerGroupOldestPending = "agentarea.broker.group.oldest_pending"
	BrokerDLQLength          = "agentarea.broker.dlq.length"
	BrokerHealth             = "agentarea.broker.health"
	RunTransitions           = "agentarea.run.transitions"
	RunDuration              = "agentarea.run.duration"
	GenAIOperationDuration   = "gen_ai.client.operation.duration"
	GenAITokenUsage          = "gen_ai.client.token.usage"
	GenAITimeToFirstChunk    = "gen_ai.client.operation.time_to_first_chunk"
	LLMInFlight              = "agentarea.llm.in_flight"
	ToolCalls                = "agentarea.tool.calls"
	ToolCallDuration         = "agentarea.tool.call.duration"
	ToolInFlight             = "agentarea.tool.in_flight"
	ToolOldestInFlight       = "agentarea.tool.oldest_in_flight"
	MCPClientDuration        = "mcp.client.operation.duration"
	MCPEraRenegotiated       = "agentarea.mcp.client.era_renegotiated"
	MCPDispatchStampDropped  = "agentarea.mcp.dispatch_stamp.dropped"

	MCPColdStartDuration = "agentarea.mcp.cold_start.duration"
	MCPColdStarts        = "agentarea.mcp.cold_starts"
	MCPGatewayDuration   = "agentarea.mcp.gateway.request.duration"
	MCPGatewayRequests   = "agentarea.mcp.gateway.requests"
	MCPGatewayInFlight   = "agentarea.mcp.gateway.in_flight"
	MCPGatewayOldest     = "agentarea.mcp.gateway.oldest_in_flight"
	MCPInstances         = "agentarea.mcp.instances"
	MCPIdleReaps         = "agentarea.mcp.idle_reaps"
	MCPUpstreamResponses = "agentarea.mcp.upstream.responses"

	EventPolls          = "agentarea.event.polls"
	EventPollDuration   = "agentarea.event.poll.duration"
	EventItemsPublished = "agentarea.event.items_published"
	EventPollers        = "agentarea.event.pollers"
)

// Attribute keys the instruments keep; every value is a closed set
// declared in code. Instance, workspace and task identities are never
// attributes: logs and traces carry them.
const (
	AttrHTTPMethod     = "http.request.method"
	AttrHTTPRoute      = "http.route"
	AttrHTTPStatusCode = "http.response.status_code"
	AttrErrorType      = "error.type"
	AttrGenAIProvider  = "gen_ai.provider.name"
	AttrGenAIModel     = "gen_ai.request.model"
	AttrGenAIOperation = "gen_ai.operation.name"
	AttrGenAITokenType = "gen_ai.token.type"
	AttrLLMPurpose     = "agentarea.llm.purpose"
	AttrToolKind       = "agentarea.tool.kind"
	AttrMCPMethod      = "mcp.method.name"
	AttrPath           = "path"
	AttrOutcome        = "outcome"
	AttrOperation      = "operation"
	AttrStream         = "stream"
	AttrGroup          = "group"
	AttrStatus         = "status"
	AttrFailureReason  = "failure_reason"
	AttrPhase          = "phase"
	AttrReason         = "reason"
	AttrPlane          = "plane"
	AttrCold           = "cold"
	AttrState          = "state"
	AttrTransport      = "transport"
)

// InstrumentPolicy is the attribute keys an instrument keeps and, for a
// histogram, its bucket boundaries.
type InstrumentPolicy struct {
	Name       string
	Attributes []string
	Buckets    []float64
}

func httpBuckets() []float64 {
	return []float64{0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30}
}

func toolBuckets() []float64 {
	return []float64{0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 900, 1800}
}

// Instruments is the exported instrument table.
func Instruments() []InstrumentPolicy {
	genAI := []string{AttrGenAIProvider, AttrGenAIModel, AttrGenAIOperation, AttrLLMPurpose}
	tool := []string{AttrToolKind, AttrPath}
	group := []string{AttrStream, AttrGroup}
	with := func(base []string, more ...string) []string { return append(append([]string(nil), base...), more...) }
	return []InstrumentPolicy{
		{HTTPServerDuration, []string{AttrHTTPMethod, AttrHTTPRoute, AttrHTTPStatusCode, AttrErrorType}, httpBuckets()},
		{HTTPClientDuration, []string{AttrHTTPMethod, AttrHTTPStatusCode, AttrErrorType}, httpBuckets()},
		{ProcessUptime, nil, nil},
		{AuthzDuration, []string{AttrOperation}, httpBuckets()},
		{BrokerGroupLag, group, nil},
		{BrokerGroupPending, group, nil},
		{BrokerGroupOldestPending, group, nil},
		{BrokerDLQLength, []string{AttrStream}, nil},
		{BrokerHealth, nil, nil},
		{RunTransitions, []string{AttrStatus, AttrFailureReason}, nil},
		{RunDuration, []string{AttrStatus}, []float64{5, 15, 30, 60, 120, 300, 600, 1800, 3600, 7200, 21600}},
		{GenAIOperationDuration, with(genAI, AttrErrorType), []float64{0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300, 600}},
		{GenAITokenUsage, with(genAI, AttrGenAITokenType), []float64{1, 4, 16, 64, 256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304}},
		{GenAITimeToFirstChunk, with(genAI), []float64{0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60}},
		{LLMInFlight, with(genAI), nil},
		{ToolCalls, with(tool, AttrOutcome), nil},
		{ToolCallDuration, with(tool, AttrOutcome), toolBuckets()},
		{ToolInFlight, with(tool), nil},
		{ToolOldestInFlight, with(tool), nil},
		{MCPClientDuration, []string{AttrMCPMethod, AttrErrorType}, toolBuckets()},
		{MCPEraRenegotiated, []string{AttrErrorType}, nil},
		{MCPDispatchStampDropped, nil, nil},

		{MCPColdStartDuration, []string{AttrPhase, AttrOutcome, AttrPlane}, []float64{1, 2, 5, 8, 10, 15, 20, 30, 45, 60, 120, 300}},
		{MCPColdStarts, []string{AttrOutcome, AttrReason, AttrPlane}, nil},
		{MCPGatewayDuration, []string{AttrMCPMethod, AttrStatus, AttrCold}, toolBuckets()},
		{MCPGatewayRequests, []string{AttrMCPMethod, AttrStatus, AttrCold}, nil},
		{MCPGatewayInFlight, nil, nil},
		{MCPGatewayOldest, nil, nil},
		{MCPInstances, []string{AttrState}, nil},
		{MCPIdleReaps, nil, nil},
		{MCPUpstreamResponses, []string{AttrStatus}, nil},

		{EventPolls, []string{AttrTransport, AttrOutcome}, nil},
		{EventPollDuration, []string{AttrTransport}, httpBuckets()},
		{EventItemsPublished, []string{AttrTransport}, nil},
		{EventPollers, []string{AttrState}, nil},
	}
}

// MeterScope is the instrumentation scope of Go instruments; Python names
// a meter per module (agentarea.authz, agentarea.process), which the
// exported series do not carry as a label.
const MeterScope = "github.com/agentarea/agentarea/agentarea-go"
