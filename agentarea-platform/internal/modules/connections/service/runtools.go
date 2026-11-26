package service

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"
	"sync"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/toolname"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

//nolint:gochecknoglobals // the embedded contract, decoded once per process
var loadCodeToolsets = sync.OnceValues(CodeToolsets)

// runTools is one resolution: what has been offered so far.
type runTools struct {
	out    api.RunToolSet
	labels map[string]string
}

func (r *runTools) bind(name string, def runsapi.ToolDefinition, b runsapi.ToolBinding, explicit bool) error {
	if prev, ok := r.out.Bindings[name]; ok {
		return fmt.Errorf("%w: two tools of the agent are offered to the model as %q (%s and %s); rename or detach one",
			api.ErrToolsRefused, name, bindingRef(prev), bindingRef(b))
	}
	r.out.Bindings[name] = b
	if explicit {
		r.out.Tools = append(r.out.Tools, def)
	}
	return nil
}

func bindingRef(b runsapi.ToolBinding) string {
	switch {
	case b.MCP != nil:
		return toolname.MCPToolTarget(b.MCP.InstanceID, b.MCP.RawName)
	case b.OpenAPI != nil:
		return toolname.OpenAPIToolTarget(b.OpenAPI.ConnectionID, b.OpenAPI.OperationID)
	case b.Code != nil:
		return b.Code.Namespace + "." + b.Code.Method
	}
	return b.Source
}

// claimLabel is claim_server_label: same-named servers get an id suffix.
func (r *runTools) claimLabel(instanceID, instanceName string) string {
	label := toolname.ServerLabel(instanceName)
	if owner, ok := r.labels[label]; ok && owner != instanceID {
		label = label + "_" + strings.ReplaceAll(instanceID, "-", "")[:6]
	}
	r.labels[label] = instanceID
	return label
}

// RunTools is the run's tool resolution (config.py _resolve_task_resources,
// ToolManager.discover_available_tools_split / discover_tool_providers /
// openapi_operation_tools): the agent's connections it may use, the
// connections selected for the run, then each tool config's tools.
func (s *Service) RunTools(ctx context.Context, req api.RunToolsRequest) (api.RunToolSet, error) {
	ws, err := scope.NewWorkspace(req.WorkspaceID, "")
	if err != nil {
		return api.RunToolSet{}, err
	}
	if s.d.Graph == nil {
		return api.RunToolSet{}, errors.New("run tool resolution needs the authorization graph")
	}
	configs := slices.Clone(req.Agent.Tools)
	if err := s.requireUsable(ctx, ws, req.Agent, configs); err != nil {
		return api.RunToolSet{}, err
	}
	if configs, err = s.withSelected(ctx, ws, req.UserID, configs, req.MCPInstanceIDs); err != nil {
		return api.RunToolSet{}, err
	}
	r := &runTools{out: api.RunToolSet{Tools: []runsapi.ToolDefinition{}, SearchableTools: []runsapi.SearchableTool{},
		ToolProviders: []runsapi.ToolProvider{}, Bindings: map[string]runsapi.ToolBinding{}, OpenAPIOperationTools: map[string][]string{}},
		labels: map[string]string{}}
	for _, c := range configs {
		if c.Name == "" {
			s.d.Log.WarnContext(ctx, "skipping a tool with no name", "type", c.Type)
			continue
		}
		var err error
		switch c.Type {
		case "code":
			err = s.codeTools(ctx, r, c)
		case "mcp":
			err = s.mcpTools(ctx, ws, r, c)
		case "openapi":
			err = s.openAPITools(ctx, ws, req.Agent, r, c)
		case "agent":
			// Delegates, local and remote, are offered by runs.
		default:
			s.d.Log.WarnContext(ctx, "unknown tool type", "type", c.Type, "name", c.Name)
		}
		if err != nil {
			return api.RunToolSet{}, err
		}
	}
	return r.out, nil
}

// connectionRef is the connection an MCP or OpenAPI config names by id (_tool_connection).
func connectionRef(c runsapi.ToolConfig) (kind, id string, ok bool) {
	switch c.Type {
	case "mcp":
		kind, id = "mcp_instance", c.Name
	case "openapi":
		kind, id = "openapi_connection", c.Settings.OpenAPIConnectionID
	default:
		return "", "", false
	}
	parsed, err := uuid.Parse(id)
	if err != nil {
		return "", "", false
	}
	return kind, parsed.String(), true
}

// requireUsable is _require_usable_connections: the agent may call through
// each connection it names, unless the platform manages it.
func (s *Service) requireUsable(ctx context.Context, ws scope.Workspace, agent runsapi.AgentSpec, configs []runsapi.ToolConfig) error {
	for _, c := range configs {
		kind, id, ok := connectionRef(c)
		if !ok {
			continue
		}
		allowed, err := s.agentMayUse(ctx, agent.ID, kind, id, func() (bool, error) { return s.platformManaged(ctx, ws, kind, id) })
		if err != nil {
			return err
		}
		if !allowed {
			return notLent(agent, id)
		}
	}
	return nil
}

func notLent(agent runsapi.AgentSpec, id string) error {
	return fmt.Errorf("%w: Agent %q may not call through connection %s: it is someone's personal connection that was not lent "+
		"to this agent. Its owner can share it with the workspace or attach it to the agent", api.ErrToolsRefused, agent.Name, id)
}

// agentMayUse is the one test of a run calling through a connection: the
// agent holds use_connection on it, or the platform manages it.
func (s *Service) agentMayUse(ctx context.Context, agentID, kind, id string, managed func() (bool, error)) (bool, error) {
	if s.d.Graph == nil {
		return false, errors.New("calling through a connection needs the authorization graph")
	}
	if agentID != "" {
		allowed, err := s.perms.Check(ctx, "Agent:"+agentID, "use_connection", kind, id)
		if err != nil || allowed {
			return allowed, err
		}
	}
	return managed()
}

func (s *Service) platformManaged(ctx context.Context, ws scope.Workspace, kind, id string) (bool, error) {
	managed := false
	err := s.readWS(ctx, ws, func(sess db.Session) error {
		uid := uuid.MustParse(id)
		if kind == "mcp_instance" {
			inst, ok, err := s.d.Instances.Get(ctx, sess, uid)
			managed = ok && inst.PlatformManaged()
			return err
		}
		conn, ok, err := s.d.Connections.Get(ctx, sess, uid)
		managed = ok && conn.PlatformManaged()
		return err
	})
	return managed, err
}

func (s *Service) readWS(ctx context.Context, ws scope.Workspace, fn func(db.Session) error) error {
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return err
	}
	defer release()
	return fn(sess)
}

// withSelected adds the MCP instances selected for the run: each must be
// visible and one the starter may use; a config already naming it (by id,
// or by name, which binds it) keeps its restriction.
func (s *Service) withSelected(ctx context.Context, ws scope.Workspace, starter string, configs []runsapi.ToolConfig, ids []string) ([]runsapi.ToolConfig, error) {
	seen := map[string]bool{}
	for _, raw := range ids {
		id, err := uuid.Parse(raw)
		if err != nil {
			return nil, fmt.Errorf("%w: invalid task mcps reference", api.ErrToolsNotFound)
		}
		if seen[id.String()] {
			continue
		}
		seen[id.String()] = true
		inst, err := s.instanceIn(ctx, ws, id)
		var nf *domain.NotFound
		if errors.As(err, &nf) {
			return nil, fmt.Errorf("%w: Selected task MCP is unavailable", api.ErrToolsNotFound)
		}
		if err != nil {
			return nil, err
		}
		if !inst.PlatformManaged() {
			ok, err := s.perms.Check(ctx, "User:"+starter, "use_connection", "mcp_instance", inst.ID)
			if err != nil {
				return nil, err
			}
			if !ok {
				return nil, fmt.Errorf("%w: The MCP connection %q selected for this run is someone else's personal connection",
					api.ErrToolsRefused, inst.Name)
			}
		}
		inherited := false
		for i, c := range configs {
			if c.Type != "mcp" {
				continue
			}
			if c.Name == inst.Name {
				configs[i].Name = inst.ID
				inherited = true
				break
			}
			if ref, err := uuid.Parse(c.Name); err == nil && ref.String() == inst.ID {
				inherited = true
				break
			}
		}
		if !inherited {
			configs = append(configs, runsapi.ToolConfig{Type: "mcp", Name: inst.ID})
		}
	}
	return configs, nil
}

func (s *Service) codeTools(ctx context.Context, r *runTools, c runsapi.ToolConfig) error {
	all, err := loadCodeToolsets()
	if err != nil {
		return err
	}
	ts, ok := all[c.Name]
	if !ok {
		ts, ok = all["agentarea/"+c.Name]
	}
	if !ok {
		s.d.Log.WarnContext(ctx, "unknown code tool requested", "name", c.Name)
		return nil
	}
	provider := runsapi.ToolProvider{Name: c.Name, ProviderType: "code", Description: ts.Description}
	for _, m := range ts.Methods {
		if slices.Contains(c.Settings.DisabledMethods, m.Method) {
			continue
		}
		name := ts.ToolName(m.Method)
		def := runsapi.ToolDefinition{Name: name, Description: m.Description, Parameters: m.Parameters}
		b := runsapi.ToolBinding{Source: "code", PolicyNames: []string{ts.Namespace, ts.ShortName()},
			Code: &runsapi.CodeBinding{Namespace: ts.Namespace, Method: m.Method, DisabledMethods: c.Settings.DisabledMethods,
				ImageModelID: c.Settings.ImageModelID, VideoModelID: c.Settings.VideoModelID, Models: c.Settings.Models}}
		if err := r.bind(name, def, b, true); err != nil {
			return err
		}
		provider.Tools = append(provider.Tools, def)
	}
	if len(provider.Tools) > 0 {
		r.out.ToolProviders = append(r.out.ToolProviders, provider)
	}
	return nil
}

// instanceTools are an instance's pinned tools (ADR-0032): its stored
// snapshot, taken by a verification when it has none yet. Nil when the
// instance is not verified.
func (s *Service) instanceTools(ctx context.Context, ws scope.Workspace, inst domain.Instance) ([]any, error) {
	if inst.Transport == domain.TransportBundle {
		var members map[string]domain.Instance
		err := s.readWS(ctx, ws, func(sess db.Session) error {
			var err error
			members, err = s.d.Instances.GetMany(ctx, sess, parseIDs(domain.BundleMembers(inst)))
			return err
		})
		if err != nil {
			return nil, err
		}
		if domain.DeriveBundleVerification(inst, members, s.d.Now()).Status != domain.VerifySucceeded {
			return nil, nil
		}
		return inst.AvailableTools(), nil
	}
	if inst.Verification.Status != domain.VerifySucceeded {
		return nil, nil
	}
	if tools := inst.AvailableTools(); tools != nil || inst.ToolsSet {
		return tools, nil
	}
	if inst.PlatformManaged() {
		return nil, nil
	}
	s.d.Log.InfoContext(ctx, "pinning the tools of an MCP instance that has no snapshot", "instance_id", inst.ID)
	v, err := s.verifyInstance(ctx, ws, inst, false)
	if err != nil {
		return nil, err
	}
	if v.Status != domain.VerifySucceeded {
		return nil, nil
	}
	pinned, err := s.instanceIn(ctx, ws, uuid.MustParse(inst.ID))
	if err != nil {
		return nil, err
	}
	return pinned.AvailableTools(), nil
}

func parseIDs(ids []string) []uuid.UUID {
	out := make([]uuid.UUID, 0, len(ids))
	for _, id := range ids {
		if u, err := uuid.Parse(id); err == nil {
			out = append(out, u)
		}
	}
	return out
}

func toolSchema(t map[string]any) map[string]any {
	for _, k := range []string{"inputSchema", "schema", "parameters"} {
		if m, ok := t[k].(map[string]any); ok && len(m) > 0 {
			return m
		}
	}
	return map[string]any{"type": "object", "properties": map[string]any{}}
}

// mcpTools is McpToolBuilder: the instance the config names by id, its
// pinned, model-visible tools narrowed by allowed_tools, under
// mcp__<server>__<tool>.
func (s *Service) mcpTools(ctx context.Context, ws scope.Workspace, r *runTools, c runsapi.ToolConfig) error {
	id, err := uuid.Parse(c.Name)
	if err != nil {
		s.d.Log.WarnContext(ctx, "MCP tool names no connection id; re-save the agent to bind it", "name", c.Name)
		return nil
	}
	inst, err := s.instanceIn(ctx, ws, id)
	var nf *domain.NotFound
	if errors.As(err, &nf) {
		s.d.Log.WarnContext(ctx, "MCP server instance not found", "instance_id", c.Name)
		return nil
	}
	if err != nil {
		return err
	}
	listed, err := s.instanceTools(ctx, ws, inst)
	if err != nil {
		return err
	}
	if listed == nil {
		s.d.Log.InfoContext(ctx, "MCP instance is not verified; its tools are not offered", "instance_id", inst.ID, "status", inst.Verification.Status)
		return nil
	}
	label := r.claimLabel(inst.ID, inst.Name)
	desc := "MCP server " + inst.Name
	if inst.Description != nil && *inst.Description != "" {
		desc = *inst.Description
	}
	provider := runsapi.ToolProvider{Name: label, ProviderType: "mcp", Description: desc}
	for _, entry := range listed {
		t, ok := entry.(map[string]any)
		if !ok {
			continue
		}
		raw := toolName(t)
		if raw == "" || !visibility(t)["model"] {
			continue
		}
		if c.Settings.AllowedTools != nil && !slices.Contains(c.Settings.AllowedTools, raw) {
			continue
		}
		description, _ := t["description"].(string)
		if description == "" {
			description = "MCP tool: " + raw
		}
		name := toolname.QualifyMCPToolName(label, raw)
		def := runsapi.ToolDefinition{Name: name, Description: description, Parameters: toolSchema(t)}
		policy := []string{toolname.MCPToolTarget(inst.ID, raw)}
		if c.Name != inst.ID {
			policy = append(policy, toolname.MCPToolTarget(c.Name, raw))
		}
		b := runsapi.ToolBinding{Source: "mcp", PolicyNames: policy,
			RestrictingNames: []string{toolname.MCPToolTarget(inst.Name, raw), raw},
			MCP: &runsapi.MCPBinding{InstanceID: inst.ID, InstanceName: inst.Name, AttachmentRef: c.Name, RawName: raw,
				ServerName: inst.Name, OpensApp: uiResourceURI(t)}}
		if inst.AuthConfigID != nil {
			b.MCP.AuthConfigID = *inst.AuthConfigID
		}
		if err := r.bind(name, def, b, true); err != nil {
			return err
		}
		provider.Tools = append(provider.Tools, def)
	}
	if len(provider.Tools) > 0 {
		r.out.ToolProviders = append(r.out.ToolProviders, provider)
	}
	return nil
}

// openAPIConnection is _resolve_openapi_connection: by id, else the
// connection with exactly that name, among those the agent may use. A match
// it may not use refuses the run.
func (s *Service) openAPIConnection(ctx context.Context, ws scope.Workspace, agent runsapi.AgentSpec, ref string) (domain.Connection, bool, error) {
	var matches []domain.Connection
	err := s.readWS(ctx, ws, func(sess db.Session) error {
		if id, err := uuid.Parse(ref); err == nil {
			c, ok, err := s.d.Connections.Get(ctx, sess, id)
			if err != nil || ok {
				matches = append(matches, c)
				return err
			}
		}
		pattern := ref
		rows, err := s.d.Connections.List(ctx, sess, ConnectionFilter{Pattern: &pattern}, 1000, 0)
		if err != nil {
			return err
		}
		for _, c := range rows {
			if c.Name == ref {
				matches = append(matches, c)
			}
		}
		return nil
	})
	if err != nil {
		return domain.Connection{}, false, err
	}
	for _, c := range matches {
		allowed, err := s.agentMayUse(ctx, agent.ID, "openapi_connection", c.ID, func() (bool, error) { return c.PlatformManaged(), nil })
		if err != nil {
			return domain.Connection{}, false, err
		}
		if allowed {
			return c, true, nil
		}
	}
	if len(matches) > 0 {
		return domain.Connection{}, false, notLent(agent, matches[0].ID)
	}
	return domain.Connection{}, false, nil
}

// openAPITools is OpenApiToolBuilder: the connection's operations narrowed
// by allowed_tools, explicit or, with load_mode searchable, held back for load_tools.
func (s *Service) openAPITools(ctx context.Context, ws scope.Workspace, agent runsapi.AgentSpec, r *runTools, c runsapi.ToolConfig) error {
	ref := c.Settings.OpenAPIConnectionID
	if ref == "" {
		ref = c.Name
	}
	conn, ok, err := s.openAPIConnection(ctx, ws, agent, ref)
	if err != nil {
		return err
	}
	if !ok {
		s.d.Log.WarnContext(ctx, "OpenAPI connection not found", "connection", ref)
		r.out.OpenAPIOperationTools[c.Name] = []string{}
		return nil
	}
	searchable := c.Settings.LoadMode == "searchable"
	desc := "OpenAPI connection " + conn.Name
	if conn.Description != nil && *conn.Description != "" {
		desc = *conn.Description
	}
	provider := runsapi.ToolProvider{Name: c.Name, ProviderType: "openapi", Description: desc}
	names := []string{}
	for _, op := range connectionOperations(conn) {
		if c.Settings.AllowedTools != nil && !slices.Contains(c.Settings.AllowedTools, op.Operation) {
			continue
		}
		description := op.Description
		if description == "" {
			description = "OpenAPI operation " + op.Operation
		}
		def := runsapi.ToolDefinition{Name: op.Name, Description: description, Parameters: op.InputSchema}
		_, identity := OpenAPIToolNames(conn.ID, conn.Name, op.Operation)
		b := runsapi.ToolBinding{Source: "openapi", PolicyNames: identity.Aliases, RestrictingNames: identity.Restricting,
			OpenAPI: &runsapi.OpenAPIBinding{ConnectionID: conn.ID, ConnectionName: conn.Name, OperationID: op.Operation, BaseURL: conn.BaseURL}}
		if conn.AuthConfigID != nil {
			b.OpenAPI.AuthConfigID = *conn.AuthConfigID
		}
		if err := r.bind(op.Name, def, b, !searchable); err != nil {
			return err
		}
		if searchable {
			r.out.SearchableTools = append(r.out.SearchableTools, runsapi.SearchableTool{Name: op.Name, Description: description,
				ConnectionID: conn.ID, SourceType: "openapi", Schema: map[string]any{"type": "function",
					"function": map[string]any{"name": op.Name, "description": description, "parameters": op.InputSchema}}})
		}
		provider.Tools = append(provider.Tools, def)
		names = append(names, op.Name)
	}
	r.out.OpenAPIOperationTools[c.Name] = names
	if len(provider.Tools) > 0 {
		r.out.ToolProviders = append(r.out.ToolProviders, provider)
	}
	return nil
}
