package app

// role is one subcommand: one deployed process (api, worker, event-service,
// mcp-manager, sandbox-runner, operator, ...). Every role talks to one database.
type role struct {
	name           string
	summary        string
	serviceAccount string
	// lands says when the role is implemented; until then it exits with
	// ErrNotImplemented.
	lands string
}

// roles is the role table (layout.md section 7). A function, not a package
// variable (rule 6).
func roles() []role {
	return []role{
		{name: "serve", summary: "HTTP API",
			serviceAccount: "agentarea-serve"},
		{name: "worker", summary: "durable workflows and activities",
			serviceAccount: "agentarea-worker"},
		{name: "events", summary: "bus consumers, pollers, the outbox relay",
			serviceAccount: "agentarea-events"},
		{name: "mcp", summary: "MCP gateway and MCP workload lifecycle; the sandbox control API",
			serviceAccount: "agentarea-mcp"},
		{name: "sandbox", summary: "sandbox execution consumer (sandbox-runner)",
			serviceAccount: "agentarea-sandbox"},
		{name: "operator", summary: "declared providers, platform connections and egress exits (CRDs)",
			serviceAccount: "agentarea-operator"},
		{name: "runner", summary: "CLI-harness runner", lands: "phase 6: runner"},
		{name: "all", summary: "serve, worker, events and the MCP runtime in one process, one listener",
			serviceAccount: "agentarea-all"},
		{name: "migrate", summary: "apply the core migration set, then extension sets",
			serviceAccount: "agentarea-migrate"},
		{name: "openapi", summary: "print the spec the binary serves",
			lands: "phase 1 step 4: generated interfaces"},
	}
}
