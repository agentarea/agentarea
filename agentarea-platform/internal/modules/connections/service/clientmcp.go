package service

import (
	"bytes"
	"context"
	"encoding/json"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/mcpserve"
	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/mcpclient"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/mcpserver"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/toolname"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

// ClientPlatform is the platform toolsets a client carries, served as on
// /mcp/w/{workspace} (mcpserver.Platform).
type ClientPlatform interface {
	// Carried is the tools of the attached toolsets minus their disabled
	// methods; a toolset no longer served is skipped, loudly.
	Carried(ctx context.Context, c authn.Caller, attached []agentsapi.ClientToolset) ([]mcpserver.Tool, error)
	CallCarried(ctx context.Context, c authn.Caller, name string, args json.RawMessage) (any, error)
}

// EnterWorkspace puts p into the workspace reference names (authn.Gate.EnterWorkspace).
type EnterWorkspace func(ctx context.Context, p authn.Principal, reference string) (authn.Caller, error)

// ActivateSkillTool is the client endpoint's skill loader.
const ActivateSkillTool = "activate_skill"

const uiScheme = "ui://"

// ClientEndpoint is what /mcp/clients/{id} serves p (_resolve_client_scope):
// a backend that lists nothing when p reaches no such client, or a
// *mcpserver.Refusal when p may not use it.
func (s *Service) ClientEndpoint(ctx context.Context, p authn.Principal, clientID string, enter EnterWorkspace, platform ClientPlatform) (mcpserver.Backend, error) {
	id, err := uuid.Parse(clientID)
	if err != nil {
		return missingClient{}, nil
	}
	clientID = id.String()
	wsID, ok, err := s.d.ClientBundles.Locate(ctx, clientID, p.AccessibleWorkspaces)
	if err != nil {
		return nil, err
	}
	if !ok {
		return missingClient{}, nil
	}
	if err := s.authorizeClient(ctx, p, clientID); err != nil {
		return nil, err
	}
	c, err := enter(ctx, p, wsID)
	if err != nil {
		return nil, err
	}
	bundle, ok, err := s.d.ClientBundles.Bundle(ctx, c.Workspace, c.UserID, clientID)
	if err != nil {
		return nil, err
	}
	if !ok {
		return missingClient{}, nil
	}
	policy, err := s.d.Policies.Effective(ctx, c.Workspace, c.UserID)
	if err != nil {
		return nil, err
	}
	b := &clientBackend{
		s: s, c: c, clientID: clientID, clientName: bundle.Name, actorType: actorType(p, clientID),
		policy: policy, pdp: governanceapi.CompileToolRules(&policy), platform: platform, skills: bundle.Skills, platformNames: map[string]bool{},
		openapiByName: map[string]int{},
	}
	if err := s.loadClientConnections(ctx, b, bundle); err != nil {
		return nil, err
	}
	if len(bundle.Toolsets) > 0 {
		if platform == nil {
			return nil, &domain.Unavailable{Msg: "platform toolsets are not served"}
		}
		tools, err := platform.Carried(ctx, c, bundle.Toolsets)
		if err != nil {
			return nil, err
		}
		b.platformTools = tools
		for _, t := range tools {
			b.platformNames[t.Name] = true
		}
	}
	return b, nil
}

// authorizeClient is _authorize_client_access: the client itself, a turn of
// its runner, or a principal holding use on the client.
func (s *Service) authorizeClient(ctx context.Context, p authn.Principal, clientID string) error {
	if p.ClientID == clientID {
		return nil
	}
	if p.BoundTaskID != "" {
		if p.TurnClientID != clientID {
			return &mcpserver.Refusal{Msg: "Not authorized for this client"}
		}
		return nil
	}
	allowed, err := s.perms.Check(ctx, p.GraphSubject(), "use", "client", clientID)
	if err != nil {
		return err
	}
	if !allowed {
		return &mcpserver.Refusal{Msg: "Not authorized for this client"}
	}
	return nil
}

func actorType(p authn.Principal, clientID string) string {
	switch {
	case p.ClientID == clientID:
		return "client"
	case p.Subject != nil && p.Subject.Kind == authn.SubjectAgent:
		return "agent"
	case p.Credential != nil && p.Credential.Kind == authn.KindAPIKey:
		return "api_key"
	}
	return "user"
}

func (s *Service) loadClientConnections(ctx context.Context, b *clientBackend, bundle agentsapi.ClientBundle) error {
	sess, release, err := s.d.DB.Read(ctx, b.c.Workspace)
	if err != nil {
		return err
	}
	defer release()
	ids := make([]uuid.UUID, 0, len(bundle.MCPInstances))
	for _, a := range bundle.MCPInstances {
		if id, err := uuid.Parse(a.ID); err == nil {
			ids = append(ids, id)
		}
	}
	instances, err := s.d.Instances.GetMany(ctx, sess, ids)
	if err != nil {
		return err
	}
	for _, a := range bundle.MCPInstances {
		inst, ok := instances[a.ID]
		if !ok {
			continue
		}
		up, err := s.UpstreamFor(ctx, b.c.Workspace, inst, nil)
		if err != nil {
			s.d.Log.ErrorContext(ctx, "Failed to resolve MCP url for instance", "instance_id", a.ID, "error", err)
			continue
		}
		b.members = append(b.members, &member{
			inst: inst, ns: toolname.AggregateNamespace(a.NamespacePrefix, inst.ID, inst.Name),
			allowed: a.AllowedTools, up: up,
		})
	}
	for _, link := range bundle.OpenAPI {
		id, err := uuid.Parse(link.ID)
		if err != nil {
			continue
		}
		conn, ok, err := s.d.Connections.Get(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			continue
		}
		ns := toolname.ServerLabel(conn.Name)
		if link.NamespacePrefix != nil && *link.NamespacePrefix != "" {
			ns = *link.NamespacePrefix
		}
		for _, t := range conn.AvailableTools {
			if t.Name == "" || (link.AllowedTools != nil && !slices.Contains(link.AllowedTools, t.Name)) {
				continue
			}
			slug := toolname.SanitizeToolName(t.Name)
			schema := t.InputSchema
			if len(schema) == 0 {
				schema = map[string]any{"type": "object", "properties": map[string]any{}}
			}
			b.addOperation(clientOperation{
				name: ns + toolname.NSSep + slug, connectionID: conn.ID, connectionName: conn.Name,
				operation: t.Name, tool: slug, description: t.Description, schema: schema,
			})
		}
	}
	return nil
}

type clientOperation struct {
	name, connectionID, connectionName, operation, tool, description string
	schema                                                           map[string]any
}

type member struct {
	inst       domain.Instance
	ns         string
	allowed    []string
	up         Upstream
	discovered bool
	tools      []map[string]any
	appOnly    map[string]bool
	carriesApp bool
}

func (m *member) serves(raw string) bool { return m.allowed == nil || slices.Contains(m.allowed, raw) }

func (m *member) servesOrApp(raw string) bool { return m.serves(raw) || m.appOnly[raw] }

type clientBackend struct {
	s                    *Service
	c                    authn.Caller
	clientID, clientName string
	actorType            string
	policy               governanceapi.Policy
	pdp                  *governanceapi.ToolRules
	platform             ClientPlatform
	platformTools        []mcpserver.Tool
	platformNames        map[string]bool
	members              []*member
	openapi              []clientOperation
	openapiByName        map[string]int
	skills               []agentsapi.ClientSkill
}

func (b *clientBackend) addOperation(op clientOperation) {
	if i, ok := b.openapiByName[op.name]; ok {
		b.openapi[i] = op
		return
	}
	b.openapiByName[op.name] = len(b.openapi)
	b.openapi = append(b.openapi, op)
}

func (b *clientBackend) operation(name string) (clientOperation, bool) {
	i, ok := b.openapiByName[name]
	if !ok {
		return clientOperation{}, false
	}
	return b.openapi[i], true
}

// discover lists a member's tools once per request: the catalog its last verification
// stored, else the server's own list. A server asleep after its idle timeout takes longer
// to start than a listing may wait, so asking it live dropped the member's tools from
// whole turns; a call still starts it, with the call's own timeout. A failure lists none.
func (b *clientBackend) discover(ctx context.Context, m *member) []map[string]any {
	if m.discovered {
		return m.tools
	}
	m.discovered = true
	if stored := storedTools(m.inst.Tools); len(stored) > 0 {
		m.tools = stored
		b.noteApp(m)
		return stored
	}
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	tools, err := withClient(ctx, m.up, func(c *mcpclient.Client) ([]map[string]any, error) { return c.ListTools(ctx) })
	if err != nil {
		b.s.d.Log.WarnContext(ctx, "Failed to discover tools from member", "instance_id", m.inst.ID, "error", err)
		tools = nil
	}
	m.tools = tools
	b.noteApp(m)
	return tools
}

func withClient[T any](ctx context.Context, up Upstream, fn func(*mcpclient.Client) (T, error)) (T, error) {
	var zero T
	c, err := mcpclient.Connect(ctx, mcpclient.Options{URL: up.URL, RoundTripper: up.Transport, Headers: up.Headers})
	if err != nil {
		return zero, err
	}
	defer c.Close()
	return fn(c)
}

func uiMeta(tool map[string]any) map[string]any {
	meta, _ := tool["_meta"].(map[string]any)
	ui, _ := meta["ui"].(map[string]any)
	return ui
}

func visibility(tool map[string]any) map[string]bool {
	ui := uiMeta(tool)
	v, ok := ui["visibility"]
	if ui == nil || !ok {
		return map[string]bool{"model": true, "app": true}
	}
	out := map[string]bool{}
	switch t := v.(type) {
	case string:
		out[t] = true
	case []any:
		for _, x := range t {
			if s, ok := x.(string); ok {
				out[s] = true
			}
		}
	}
	return out
}

func uiResourceURI(tool map[string]any) string {
	if u, ok := uiMeta(tool)["resourceUri"].(string); ok && strings.HasPrefix(u, uiScheme) {
		return u
	}
	meta, _ := tool["_meta"].(map[string]any)
	if u, ok := meta["ui/resourceUri"].(string); ok && strings.HasPrefix(u, uiScheme) {
		return u
	}
	return ""
}

func toolName(tool map[string]any) string { n, _ := tool["name"].(string); return n }

// noteApp is _note_app: the member's app is carried once a model-visible
// tool it serves opens it; its app-only tools then follow the app.
func (b *clientBackend) noteApp(m *member) {
	m.appOnly, m.carriesApp = map[string]bool{}, false
	for _, t := range m.tools {
		if visibility(t)["model"] && uiResourceURI(t) != "" && m.serves(toolName(t)) {
			m.carriesApp = true
			break
		}
	}
	if !m.carriesApp {
		return
	}
	for _, t := range m.tools {
		v := visibility(t)
		if !v["model"] && v["app"] {
			m.appOnly[toolName(t)] = true
		}
	}
}

func (b *clientBackend) appView(ctx context.Context, m *member) []map[string]any {
	var out []map[string]any
	for _, t := range b.discover(ctx, m) {
		n := toolName(t)
		if (visibility(t)["model"] && m.serves(n)) || m.appOnly[n] {
			out = append(out, t)
		}
	}
	return out
}

func namespacedURI(ns, uri string) string {
	if !strings.HasPrefix(uri, uiScheme) {
		return ""
	}
	return uiScheme + ns + "/" + uri[len(uiScheme):]
}

func (b *clientBackend) ListTools(ctx context.Context) ([]mcpserver.Tool, error) {
	tools := append([]mcpserver.Tool(nil), b.platformTools...)
	for _, m := range b.members {
		for _, t := range b.appView(ctx, m) {
			tool, err := listedMember(m, t)
			if err != nil {
				return nil, err
			}
			tools = append(tools, tool)
		}
	}
	for _, op := range b.openapi {
		schema, err := json.Marshal(op.schema)
		if err != nil {
			return nil, err
		}
		tools = append(tools, mcpserver.Tool{Tool: mcpserve.Tool{Name: op.name, Description: op.description, InputSchema: schema}})
	}
	out := make([]mcpserver.Tool, 0, len(tools)+1)
	for _, t := range tools {
		if b.decide(t.Name).Action != governanceapi.ToolDeny {
			out = append(out, t)
		}
	}
	if len(b.skills) > 0 {
		out = append(out, b.activateSkillTool())
	}
	return out, nil
}

func listedMember(m *member, t map[string]any) (mcpserver.Tool, error) {
	desc, _ := t["description"].(string)
	schema := t["inputSchema"]
	if s, ok := schema.(map[string]any); !ok || len(s) == 0 {
		schema = map[string]any{"type": "object"}
	}
	raw, err := json.Marshal(schema)
	if err != nil {
		return mcpserver.Tool{}, err
	}
	tool := mcpserver.Tool{Tool: mcpserve.Tool{Name: m.ns + toolname.NSSep + toolName(t), Description: desc, InputSchema: raw}}
	ui := map[string]any{}
	for k, v := range uiMeta(t) {
		if k != "resourceUri" {
			ui[k] = v
		}
	}
	if uri := uiResourceURI(t); uri != "" {
		ui["resourceUri"] = namespacedURI(m.ns, uri)
	}
	if len(ui) > 0 {
		tool.Meta = map[string]any{"ui": ui}
	}
	return tool, nil
}

func (b *clientBackend) activateSkillTool() mcpserver.Tool {
	names := make([]string, 0, len(b.skills))
	for _, s := range b.skills {
		names = append(names, s.Name)
	}
	schema, _ := json.Marshal(map[string]any{
		"type": "object",
		"properties": map[string]any{"skill_name": map[string]any{
			"type": "string", "enum": names, "description": "Name of the skill to activate.",
		}},
		"required": []string{"skill_name"},
	})
	return mcpserver.Tool{Tool: mcpserve.Tool{Name: ActivateSkillTool, Description: "Load full instructions for an available skill by name.", InputSchema: schema}}
}

// owner is owner_of: the member whose namespace claims name, if it serves the tool.
func (b *clientBackend) owner(name string) (*member, string, bool) {
	for _, m := range b.members {
		if raw, ok := strings.CutPrefix(name, m.ns+toolname.NSSep); ok {
			if m.servesOrApp(raw) {
				return m, raw, true
			}
			return nil, "", false
		}
	}
	return nil, "", false
}

// resolve is resolve_tool: name itself, or the one served tool whose raw
// name it is (an MCP App calls its own tools by their raw names).
func (b *clientBackend) resolve(ctx context.Context, name string) (string, error) {
	if _, _, ok := b.owner(name); ok {
		return name, nil
	}
	var matches []string
	for _, m := range b.members {
		for _, t := range b.appView(ctx, m) {
			if toolName(t) == name {
				matches = append(matches, m.ns+toolname.NSSep+name)
			}
		}
	}
	if _, _, ok := b.owner(name); ok {
		return name, nil
	}
	sort.Strings(matches)
	switch len(matches) {
	case 0:
		return "", &mcpserver.Refusal{Msg: "No member owns tool " + name}
	case 1:
		return matches[0], nil
	}
	return "", &mcpserver.Refusal{Msg: "Tool " + name + " is served by more than one connection; call one of " + strings.Join(matches, ", ")}
}

// names are the names a rule may give the tool (_policy_aliases,
// _restricting_aliases, _name_allows).
func (b *clientBackend) names(name string) governanceapi.ToolNames {
	if b.platformNames[name] {
		return governanceapi.ToolNames{NameAllows: true}
	}
	if op, ok := b.operation(name); ok {
		_, names := OpenAPIToolNames(op.connectionID, op.connectionName, op.operation)
		return names
	}
	m, raw, ok := b.owner(name)
	if !ok {
		return governanceapi.ToolNames{NameAllows: true}
	}
	return governanceapi.ToolNames{
		Aliases:     []string{toolname.MCPToolTarget(m.inst.ID, raw)},
		Restricting: toolname.MCPNarrowingNames(m.inst.Name, raw),
	}
}

func (b *clientBackend) decide(name string) governanceapi.ToolDecision {
	return b.pdp.Decide(name, b.names(name))
}

func textResult(text string, isError bool) mcpserve.Result {
	return mcpserve.Result{Content: []mcpserve.Content{{Type: "text", Text: text}}, IsError: isError}
}

func (b *clientBackend) CallTool(ctx context.Context, name string, args json.RawMessage) (any, error) {
	if name == ActivateSkillTool {
		var in struct {
			SkillName string `json:"skill_name"`
		}
		_ = json.Unmarshal(args, &in)
		return textResult(b.activateSkill(in.SkillName), false), nil
	}
	if op, ok := b.operation(name); ok {
		return b.governed(ctx, name, args, map[string]any{"openapi_connection_id": op.connectionID}, func() (any, error) {
			res, err := b.s.callConnectionTool(ctx, b.c, op.connectionID, op.operation, args, false)
			if err != nil {
				return nil, err
			}
			return mcpserve.Result{Content: []mcpserve.Content{{Type: "text", Text: res.Text}}, IsError: res.IsError, StructuredContent: res.StructuredContent}, nil
		})
	}
	if b.platformNames[name] {
		return b.governed(ctx, name, args, nil, func() (any, error) {
			return b.platform.CallCarried(ctx, b.c, name, args)
		})
	}
	resolved, err := b.resolve(ctx, name)
	if err != nil {
		return nil, err
	}
	m, raw, _ := b.owner(resolved)
	return b.governed(ctx, resolved, args, map[string]any{"mcp_instance_id": m.inst.ID}, func() (any, error) {
		up, err := b.s.UpstreamFor(ctx, b.c.Workspace, m.inst, &CallerContext{
			UserID: b.c.UserID, UserEmail: b.c.Email, ClientID: b.c.ClientID, Tool: raw,
		})
		if err != nil {
			return nil, err
		}
		var arguments map[string]any
		if err := decodeUseNumber(args, &arguments); err != nil {
			return nil, &mcpserver.Error{Code: mcpserver.CodeInvalidParams, Message: "Invalid request parameters"}
		}
		res, err := withClient(ctx, up, func(c *mcpclient.Client) (*mcpclient.CallResult, error) {
			return c.CallTool(ctx, mcpclient.Call{Name: raw, Arguments: arguments})
		})
		if err != nil {
			b.s.d.Log.WarnContext(ctx, "MCP member tool call failed", "instance_id", m.inst.ID, "tool", raw, "error", err)
			return textResult(err.Error(), true), nil
		}
		return callResultJSON(res), nil
	})
}

func (b *clientBackend) activateSkill(name string) string {
	var names []string
	for _, s := range b.skills {
		if s.Name == name {
			return `<skill_content name="` + name + `">` + "\n" + s.Content + "</skill_content>"
		}
		names = append(names, s.Name)
	}
	return "Unknown skill '" + name + "'. Available: " + strings.Join(names, ", ")
}

// governed is _layered_call: the PDP judges the call, then judged passes it
// through its approval or runs' layer before it runs.
func (b *clientBackend) governed(ctx context.Context, name string, args json.RawMessage, meta map[string]any, run func() (any, error)) (any, error) {
	d := b.decide(name)
	instanceID, connector, raw := "", "AgentArea", name
	var binding runsapi.ToolBinding
	if op, ok := b.operation(name); ok {
		connector, raw = op.connectionName, op.operation
		binding = openAPIBinding(op.connectionID, op.operation)
	} else if m, r, ok := b.owner(name); ok && !b.platformNames[name] {
		instanceID, connector, raw = m.inst.ID, m.inst.Name, r
		binding = mcpBinding(m.inst.ID, r)
	}
	held := func() runsapi.HeldCall {
		return heldCall(b.c, &b.policy, name, b.names(name), instanceID, connector, raw, b.clientName, args, d.Reason)
	}
	a := toolAudit{resourceType: "client", resourceID: b.clientID, actorType: b.actorType, name: name, args: args, extra: meta}
	out, refused, err := b.s.judged(ctx, b.c, b.clientID, a, d, held, named(binding, b.names(name)), run)
	if err != nil {
		return nil, err
	}
	if refused != "" {
		return textResult(refused, true), nil
	}
	return out, nil
}

func argumentKeys(args json.RawMessage) []string {
	var fields map[string]json.RawMessage
	_ = json.Unmarshal(args, &fields)
	keys := make([]string, 0, len(fields))
	for k := range fields {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

// auditToolCall files one verdict against the resource the call went
// through, before the call runs, in its own transaction.
func (s *Service) auditToolCall(ctx context.Context, c authn.Caller, resourceType, resourceID, actorType, name string,
	args json.RawMessage, d governanceapi.ToolDecision, extra map[string]any) error {
	if s.d.Audit == nil {
		s.d.Log.WarnContext(ctx, "Tool call not audited: no audit writer", "resource_type", resourceType, "resource_id", resourceID,
			"tool", name, "decision", string(d.Action))
		return nil
	}
	return s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, tx db.Session) error {
		return s.recordToolCall(ctx, tx, c, resourceType, resourceID, actorType, name, args, d, extra)
	})
}

// recordToolCall is _record_tool_call: the verdict's audit row in tx, argument keys only.
func (s *Service) recordToolCall(ctx context.Context, tx db.Session, c authn.Caller, resourceType, resourceID, actorType, name string,
	args json.RawMessage, d governanceapi.ToolDecision, extra map[string]any) error {
	if s.d.Audit == nil {
		s.d.Log.WarnContext(ctx, "Tool call not audited: no audit writer", "resource_type", resourceType, "resource_id", resourceID,
			"tool", name, "decision", string(d.Action))
		return nil
	}
	action := "tool.call.denied"
	if d.Allowed() {
		action = "tool.call.allowed"
	}
	meta := map[string]any{"tool": name, "decision": string(d.Action), "reason": d.Reason, "argument_keys": argumentKeys(args)}
	for k, v := range extra {
		meta[k] = v
	}
	return s.d.Audit.RecordOnce(ctx, tx, governanceapi.AuditRecord{
		EventID: s.d.NewID().String(), Action: action, ResourceType: resourceType, ResourceID: resourceID,
		ActorType: actorType, ActorID: c.UserID, Metadata: meta,
	})
}

func (b *clientBackend) ListResources(ctx context.Context) ([]json.RawMessage, error) {
	var out []json.RawMessage
	for _, m := range b.members {
		b.discover(ctx, m)
		if !m.carriesApp {
			continue
		}
		lctx, cancel := context.WithTimeout(ctx, 10*time.Second)
		resources, err := withClient(lctx, m.up, func(c *mcpclient.Client) ([]map[string]any, error) { return listResources(lctx, c) })
		cancel()
		if err != nil {
			b.s.d.Log.WarnContext(ctx, "Failed to list resources of member", "instance_id", m.inst.ID, "error", err)
			continue
		}
		for _, r := range resources {
			uri, _ := r["uri"].(string)
			ns := namespacedURI(m.ns, uri)
			if ns == "" {
				continue
			}
			r["uri"] = ns
			raw, err := json.Marshal(r)
			if err != nil {
				return nil, err
			}
			out = append(out, raw)
		}
	}
	return out, nil
}

func (b *clientBackend) ReadResource(ctx context.Context, uri string) (json.RawMessage, bool, error) {
	var m *member
	var memberURI string
	for _, cand := range b.members {
		if rest, ok := strings.CutPrefix(uri, uiScheme+cand.ns+"/"); ok {
			m, memberURI = cand, uiScheme+rest
			break
		}
	}
	if m == nil {
		return nil, false, nil
	}
	if b.discover(ctx, m); !m.carriesApp {
		return nil, false, nil
	}
	rctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	raw, err := withClient(rctx, m.up, func(c *mcpclient.Client) (json.RawMessage, error) {
		return c.Request(rctx, "resources/read", map[string]any{"uri": memberURI})
	})
	if err != nil {
		return nil, false, err
	}
	var res map[string]any
	if err := decodeUseNumber(raw, &res); err != nil {
		return nil, false, err
	}
	if contents, ok := res["contents"].([]any); ok {
		for _, c := range contents {
			if cm, ok := c.(map[string]any); ok {
				if u, _ := cm["uri"].(string); namespacedURI(m.ns, u) != "" {
					cm["uri"] = namespacedURI(m.ns, u)
				}
			}
		}
	}
	out, err := json.Marshal(res)
	return out, err == nil, err
}

func decodeUseNumber(raw []byte, v any) error {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	return dec.Decode(v)
}

// listResources is resources/list, every page.
func listResources(ctx context.Context, c *mcpclient.Client) ([]map[string]any, error) {
	var out []map[string]any
	cursor := ""
	for range 100 {
		params := map[string]any{}
		if cursor != "" {
			params["cursor"] = cursor
		}
		raw, err := c.Request(ctx, "resources/list", params)
		if err != nil {
			return nil, err
		}
		var page struct {
			Resources  []map[string]any `json:"resources"`
			NextCursor string           `json:"nextCursor"`
		}
		if err := decodeUseNumber(raw, &page); err != nil {
			return nil, err
		}
		out = append(out, page.Resources...)
		if page.NextCursor == "" || page.NextCursor == cursor {
			return out, nil
		}
		cursor = page.NextCursor
	}
	return out, nil
}

// callResultJSON is a member's tools/call result with absent fields left out.
func callResultJSON(r *mcpclient.CallResult) map[string]any {
	content := r.Content
	if content == nil {
		content = []map[string]any{}
	}
	out := map[string]any{"content": content}
	if r.StructuredContent != nil {
		out["structuredContent"] = r.StructuredContent
	}
	if r.IsError {
		out["isError"] = true
	}
	if r.Meta != nil {
		out["_meta"] = r.Meta
	}
	return out
}

// missingClient is what a request naming no client the caller reaches gets.
type missingClient struct{}

var errClientNotFound = &mcpserver.Refusal{Msg: "Client not found"}

func (missingClient) ListTools(context.Context) ([]mcpserver.Tool, error) {
	return []mcpserver.Tool{}, nil
}

func (missingClient) CallTool(context.Context, string, json.RawMessage) (any, error) {
	return nil, errClientNotFound
}

func (missingClient) ListResources(context.Context) ([]json.RawMessage, error) {
	return nil, errClientNotFound
}

func (missingClient) ReadResource(context.Context, string) (json.RawMessage, bool, error) {
	return nil, false, errClientNotFound
}

// storedTools is the tool definitions of an instance's stored catalog.
func storedTools(raw []any) []map[string]any {
	out := make([]map[string]any, 0, len(raw))
	for _, t := range raw {
		if def, ok := t.(map[string]any); ok && toolName(def) != "" {
			out = append(out, def)
		}
	}
	return out
}
