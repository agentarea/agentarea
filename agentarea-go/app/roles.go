package app

// part is one module a role runs, and what of it.
type part struct {
	module string
	runs   string
}

// role is one subcommand. Roles mirror today's processes (api, worker,
// event-service, mcp-manager, sandbox-runner, operator); every role talks to
// the one database the Python backend uses.
type role struct {
	name           string
	summary        string
	serviceAccount string
	parts          []part
	includes       []string
	// lands says when the role is implemented; until then it exits with
	// ErrNotImplemented.
	lands string
}

// roles is the role table (layout.md section 7). A function, not a package
// variable (rule 6).
func roles() []role {
	return []role{
		{name: "serve", summary: "HTTP API; during the migration a fallback proxy to Python",
			serviceAccount: "agentarea-serve",
			parts: []part{
				{"identity", "http"}, {"projects", "http"}, {"agents", "http"},
				{"catalog", "http"}, {"wallet", "http"}, {"insights", "http"},
				{"runs", "http, sse, ws"}, {"models", "http"}, {"connections", "http"},
				{"streams", "http"}, {"governance", "http"},
			}},
		{name: "worker", summary: "durable workflows and activities",
			serviceAccount: "agentarea-worker",
			parts: []part{
				{"runs", "workflows, activities"}, {"models", "activities"},
				{"connections", "activities"}, {"sandbox", "activities"},
				{"streams", "workflows"}, {"governance", "decision point"},
			}},
		{name: "events", summary: "bus consumers, pollers, the outbox relay",
			serviceAccount: "agentarea-events",
			parts: []part{
				{"streams", "router, events view, subscription changes, pollers, external delivery, task replies, platform stream, trigger outcomes"},
				{"identity", "membership removal (outbox relay)"},
			}},
		{name: "mcp", summary: "MCP gateway and MCP workload lifecycle",
			serviceAccount: "agentarea-mcp",
			parts:          []part{{"connections", "gateway, lifecycle"}, {"governance", "decision point"}}},
		{name: "sandbox", summary: "sandbox control: placement, warm pool, backends",
			serviceAccount: "agentarea-sandbox", lands: "phase 4: sandbox-runner fold-in",
			parts: []part{{"sandbox", "control"}}},
		{name: "operator", summary: "catalog and provider reconcile",
			serviceAccount: "agentarea-operator", lands: "phase 7: operator",
			parts: []part{{"catalog", "reconcile"}}},
		{name: "runner", summary: "CLI-harness runner", lands: "phase 6: runner",
			parts: []part{{"runs", "runner"}}},
		{name: "all", summary: "every role in one process, one listener",
			serviceAccount: "agentarea-all",
			includes:       []string{"serve", "operator", "worker", "events", "mcp", "sandbox"}},
		{name: "migrate", summary: "apply the core migration set, then extension sets",
			serviceAccount: "agentarea-migrate"},
		{name: "openapi", summary: "print the spec the binary serves",
			lands: "phase 1 step 4: generated interfaces"},
	}
}
