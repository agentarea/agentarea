package mcpserver

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sync"

	"github.com/agentarea/agentarea/agentarea-go/api/contract"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/mcpserve"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	connectionsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	identityapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/api"
	insightsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/insights/api"
	modelsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/models/api"
	projectsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/projects/api"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	sandboxapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
	streamsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/api"
)

// Providers are the modules behind the platform toolsets. A nil provider
// leaves its toolset unserved.
type Providers struct {
	Agents          agentsapi.Agents
	Runs            runsapi.PlatformRuns
	TaskDefs        agentsapi.TaskDefs
	Skills          agentsapi.Skills
	Projects        projectsapi.PlatformProjects
	Clients         agentsapi.Clients
	Members         identityapi.Members
	Policies        governanceapi.PlatformPolicies
	Triggers        streamsapi.PlatformTriggers
	Streams         streamsapi.PlatformStreams
	StreamEvents    streamsapi.PlatformStreamEvents
	WorkspaceFiles  sandboxapi.PlatformFiles
	Inbox           runsapi.PlatformInbox
	OpenAPI         connectionsapi.PlatformOpenAPI
	MCPServers      connectionsapi.PlatformMCPServers
	ConnectorTools  connectionsapi.PlatformConnectorTools
	LLMProviders    modelsapi.PlatformProviders
	Models          modelsapi.PlatformModels
	Secrets         governanceapi.PlatformSecrets
	Audit           governanceapi.PlatformAudit
	Network         insightsapi.PlatformNetwork
	WorkspaceConfig agentsapi.WorkspaceConfig
	// Files is the workspace file store workspaces_update reads a logo from.
	Files sandboxapi.Files
	// Slugs names a workspace entered by id alone (a run's), for the URLs tools return.
	Slugs identityapi.WorkspaceSlugs
}

// toolsetSpec is one platform toolset: its @toolset metadata, whether its
// provider is set, and its adapters.
type toolsetSpec struct {
	Name, DisplayName, Description, Plane string
	unscoped                              bool
	on                                    bool
	defs                                  func() map[string]toolDef
}

// specs are the platform toolsets in get_spanning_mcp_tools order.
func (p Providers) specs(apiURL string) []toolsetSpec {
	return []toolsetSpec{
		{"workspaces", "Workspaces", "List the workspaces you can reach, create new ones, and update their settings.", "govern", true,
			p.Members != nil, func() map[string]toolDef { return workspaceTools(p.Members, p.Files, apiURL) }},
		{"agents", "Agent Management", "Create, list, update, archive, and restore agents in the workspace.", "build", false,
			p.Agents != nil, func() map[string]toolDef { return agentsTools(p.Agents) }},
		{"runs", "Agent Runs", "Start, monitor, and manage agent execution runs.", "operate", false,
			p.Runs != nil, func() map[string]toolDef { return runsTools(p.Runs) }},
		{"task_definitions", "Saved tasks", "Save what to ask an agent, and run it on demand or from a trigger.", "operate", false,
			p.TaskDefs != nil, func() map[string]toolDef { return taskDefTools(p.TaskDefs) }},
		{"skills", "Skills", "Manage workspace skills (multi-file authoring, GitHub import, archive upload).", "build", false,
			p.Skills != nil, func() map[string]toolDef { return skillTools(p.Skills) }},
		{"projects", "Projects", "Manage projects and their skills/agents/MCP instances.", "build", false,
			p.Projects != nil, func() map[string]toolDef { return projectTools(p.Projects) }},
		{"clients", "Registered Clients", "", "federate", false,
			p.Clients != nil, func() map[string]toolDef { return clientTools(p.Clients) }},
		{"members", "Workspace Members", "List workspace members, invite people, and revoke access.", "govern", false,
			p.Members != nil, func() map[string]toolDef { return memberTools(p.Members) }},
		{"policies", "Governance Policies", "List, inspect, and write the workspace's governance policy rules.", "govern", false,
			p.Policies != nil, func() map[string]toolDef { return policyTools(p.Policies) }},
		{"triggers", "Triggers", "Schedule agents on cron expressions or run them on the events of a stream.", "build", false,
			p.Triggers != nil, func() map[string]toolDef { return triggerTools(p.Triggers) }},
		{"streams", "Event Streams", "", "build", false,
			p.Streams != nil, func() map[string]toolDef { return streamTools(p.Streams) }},
		{"stream_events", "Stream Events", "", "operate", false,
			p.StreamEvents != nil, func() map[string]toolDef { return streamEventTools(p.StreamEvents) }},
		{"workspace_files", "Workspace Files", "List, read, upload, fetch download URLs for, and delete workspace files.", "operate", false,
			p.WorkspaceFiles != nil, func() map[string]toolDef { return workspaceFileTools(p.WorkspaceFiles, p.Slugs) }},
		{"inbox", "Inbox", "Inspect agent inbox messages awaiting human input.", "operate", false,
			p.Inbox != nil, func() map[string]toolDef { return inboxTools(p.Inbox) }},
		{"openapi_connections", "OpenAPI Connections", "Manage OpenAPI connections that expose external APIs as tools.", "build", false,
			p.OpenAPI != nil, func() map[string]toolDef { return openAPITools(p.OpenAPI) }},
		{"mcp_servers", "MCP Server Management", "Start, stop, and manage MCP server instances.", "build", false,
			p.MCPServers != nil, func() map[string]toolDef { return mcpServerTools(p.MCPServers) }},
		{"tools", "Connector Tools", "Search the tools of the workspace's connectors and call them.", "operate", false,
			p.ConnectorTools != nil, func() map[string]toolDef { return connectorTools(p.ConnectorTools) }},
		{"providers", "LLM Providers", "Manage LLM provider specs and configurations.", "build", false,
			p.LLMProviders != nil, func() map[string]toolDef { return providerTools(p.LLMProviders) }},
		{"models", "Models", "Inspect model specifications and create/inspect model instances.", "build", false,
			p.Models != nil, func() map[string]toolDef { return modelTools(p.Models) }},
		{"secrets", "Secrets", "Manage workspace secrets (names only, values are encrypted).", "build", false,
			p.Secrets != nil, func() map[string]toolDef { return secretTools(p.Secrets) }},
		{"audit", "Audit Log", "Inspect workspace audit log entries.", "observe", false,
			p.Audit != nil, func() map[string]toolDef { return auditTools(p.Audit) }},
		{"network", "Network", "Inspect workspace network topology (agents, skills, MCP instances, triggers).", "observe", false,
			p.Network != nil, func() map[string]toolDef { return networkTools(p.Network) }},
		{"workspace_config", "Workspace Config", "Export workspace configuration as YAML.", "build", false,
			p.WorkspaceConfig != nil, func() map[string]toolDef { return workspaceConfigTools(p.WorkspaceConfig) }},
	}
}

//nolint:gochecknoglobals // the embedded contract, decoded once per process
var loadContract = sync.OnceValues(contract.LoadMCPTools)

// Toolsets are the adapters of the providers that are set, in the order
// get_spanning_mcp_tools lists them. apiURL is the API's public base (the MCP
// URLs the clients and workspaces tools report).
func (p Providers) Toolsets(apiURL string) ([]mcpserve.Toolset, error) {
	tools, err := loadContract()
	if err != nil {
		return nil, err
	}
	var out []mcpserve.Toolset
	for _, s := range p.specs(apiURL) {
		if !s.on {
			continue
		}
		server := tools.PlatformPinned
		if s.unscoped {
			server = tools.PlatformSpanning
		}
		ts, err := newContractToolset(server, s.Name, "agentarea/"+s.Name, s.defs())
		if err != nil {
			return nil, err
		}
		ts.unscoped = s.unscoped
		out = append(out, ts)
	}
	return out, nil
}

// Effects of a tool method (tool_method effect=).
const (
	effectRead        = "read"
	effectWrite       = "write"
	effectDestructive = "destructive"
	effectPrivileged  = "privileged"
)

// toolDef is one tool method: its title, behaviour and call. call gets the
// caller in the tool's workspace (an unscoped toolset's: the principal with
// no workspace) and the arguments, the workspace argument already taken.
type toolDef struct {
	title      string
	effect     string
	idempotent bool
	openWorld  bool
	call       func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error)
}

// annotations is _annotations: the effect's hints, idempotency and the
// toolset's closed world (every platform toolset is open_world = False).
func (d toolDef) annotations() map[string]any {
	a := map[string]any{"openWorldHint": d.openWorld}
	switch d.effect {
	case effectRead:
		a["readOnlyHint"] = true
	case effectWrite:
		a["readOnlyHint"], a["destructiveHint"] = false, false
	case effectDestructive, effectPrivileged:
		a["readOnlyHint"], a["destructiveHint"] = false, true
	}
	if d.idempotent {
		a["idempotentHint"] = true
	}
	return a
}

// contractToolset serves one toolset's tools as the contract lists them.
type contractToolset struct {
	name, namespace string
	unscoped        bool
	tools           []mcpserve.Tool
	defs            map[string]toolDef
}

func newContractToolset(server contract.MCPServer, name, namespace string, defs map[string]toolDef) (*contractToolset, error) {
	ts := &contractToolset{name: name, namespace: namespace, defs: map[string]toolDef{}}
	for _, t := range server.Tools {
		if t.Toolset != name {
			continue
		}
		method := t.Name[len(name)+1:]
		d, ok := defs[method]
		if !ok {
			return nil, fmt.Errorf("toolset %s: the contract lists %s, which has no adapter", name, t.Name)
		}
		ts.defs[t.Name] = d
		ts.tools = append(ts.tools, mcpserve.Tool{
			Name: t.Name, Title: d.title, Description: t.Description, InputSchema: t.InputSchema,
			Annotations: d.annotations(),
		})
	}
	if len(ts.tools) != len(defs) {
		return nil, fmt.Errorf("toolset %s: adapters name tools the contract does not list", name)
	}
	return ts, nil
}

func (t *contractToolset) Name() string      { return t.name }
func (t *contractToolset) Namespace() string { return t.namespace }
func (t *contractToolset) Unscoped() bool    { return t.unscoped }

func (t *contractToolset) Tools(context.Context, authn.Principal) ([]mcpserve.Tool, error) {
	return t.tools, nil
}

func (t *contractToolset) Call(ctx context.Context, p authn.Principal, tool string, args json.RawMessage) (mcpserve.Result, error) {
	d, ok := t.defs[tool]
	if !ok {
		return errorResult("Unknown tool: " + tool), nil
	}
	c := authn.Caller{Principal: p}
	if !t.unscoped {
		var ok bool
		if c, ok = authn.CallerFrom(ctx); !ok {
			return mcpserve.Result{}, authn.ErrWorkspaceNotSelected
		}
	}
	if len(args) == 0 || string(args) == "null" {
		args = json.RawMessage(`{}`)
	}
	out, err := d.call(ctx, c, args)
	if errors.Is(err, authz.ErrNotWorkspaceAdmin) {
		return mcpserve.Result{}, &toolError{authz.NotAdminDetail}
	}
	if err != nil {
		return mcpserve.Result{}, err
	}
	return structured(out)
}

// structured is a tool's output as FastMCP publishes it: the JSON text, and
// the value as structured content (a value that is not an object wrapped as
// {"result": value}).
func structured(v any) (mcpserve.Result, error) {
	raw, err := json.Marshal(v)
	if err != nil {
		return mcpserve.Result{}, err
	}
	var decoded any
	if err := json.Unmarshal(raw, &decoded); err != nil {
		return mcpserve.Result{}, err
	}
	sc := decoded
	if _, isObject := decoded.(map[string]any); !isObject {
		sc = map[string]any{"result": decoded}
	}
	return mcpserve.Result{Content: []mcpserve.Content{{Type: "text", Text: string(raw)}}, StructuredContent: sc}, nil
}

// toolError is a ToolError: the text the caller reads as the failed result.
type toolError struct{ msg string }

func (e *toolError) Error() string { return e.msg }

// decodeArgs reads a tool's arguments into T; unknown keys are ignored as
// pydantic ignores them.
func decodeArgs[T any](args json.RawMessage) (T, error) {
	var v T
	if err := json.Unmarshal(args, &v); err != nil {
		return v, &toolError{"Invalid arguments: " + err.Error()}
	}
	return v, nil
}

// patchArgs is args without the keys drop names and without every key in
// nullable whose value is null: a PATCH document of what the caller set.
func patchArgs(args json.RawMessage, drop []string, nullable []string) (json.RawMessage, error) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(args, &fields); err != nil {
		return nil, &toolError{"Invalid arguments: " + err.Error()}
	}
	for _, k := range drop {
		delete(fields, k)
	}
	for _, k := range nullable {
		if v, ok := fields[k]; ok && string(v) == "null" {
			delete(fields, k)
		}
	}
	return json.Marshal(fields)
}

func workspaceConfigTools(w agentsapi.WorkspaceConfig) map[string]toolDef {
	return map[string]toolDef{
		"export": {title: "Export workspace config", effect: effectRead, call: func(ctx context.Context, c authn.Caller, _ json.RawMessage) (any, error) {
			yaml, err := w.Export(ctx, c)
			if err != nil {
				return nil, err
			}
			return map[string]any{"yaml": yaml}, nil
		}},
	}
}
