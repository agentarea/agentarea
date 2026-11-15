package service

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
)

// Misc serves GET /agents/tools, the workspace export and the agent presets.
type Misc struct {
	s *Service
	d MiscDeps
}

// NewMisc builds the service over the agents service.
func NewMisc(s *Service, d MiscDeps) *Misc { return &Misc{s: s, d: d} }

// ToolsQuery is get_all_tools' query: include as sent, mcp_instance_id canonical or "".
type ToolsQuery struct {
	Include       string
	MCPInstanceID string
}

// Tools is get_all_tools: the ToolResponse list.
func (m *Misc) Tools(ctx context.Context, c authn.Caller, q ToolsQuery) ([]wirejson.Object, error) {
	types := map[string]bool{}
	for _, t := range strings.Split(q.Include, ",") {
		types[strings.TrimFunc(t, isPySpace)] = true
	}
	out := []wirejson.Object{}
	if types["code"] {
		if m.s.d.CodeTools == nil {
			return nil, &UnwiredError{Feature: "the code toolset catalogue"}
		}
		for _, ts := range m.s.d.CodeTools.Metadata() {
			out = append(out, toolsCodeJSON(ts))
		}
	}
	if types["mcp"] {
		if m.d.ToolsMCP == nil {
			return nil, &UnwiredError{Feature: "MCP tools of the workspace's connections"}
		}
		instances, err := m.d.ToolsMCP.InstanceTools(ctx, c, q.MCPInstanceID)
		if err != nil {
			return nil, err
		}
		for _, inst := range instances {
			for _, tool := range inst.Tools {
				o, ok, err := toolsMCPJSON(tool, inst)
				if errors.Is(err, errToolsMalformed) {
					m.s.d.Log.WarnContext(ctx, "Skipping an MCP tool that is not a valid tool entry", "mcp_instance_id", inst.ID)
					continue
				}
				if err != nil {
					return nil, err
				}
				if ok {
					out = append(out, o)
				}
			}
		}
	}
	return out, nil
}

func toolsNullable(s *string) any {
	if s == nil {
		return nil
	}
	return *s
}

func toolsCodeJSON(ts CodeToolset) wirejson.Object {
	display := ts.DisplayName
	if display == "" {
		display = ts.Name
	}
	methods := make([]any, len(ts.Methods))
	for i, mt := range ts.Methods {
		methods[i] = wirejson.Object{{Key: "name", Value: mt.Name}, {Key: "display_name", Value: mt.DisplayName},
			{Key: "description", Value: mt.Description}, {Key: "effect", Value: toolsNullable(mt.Effect)},
			{Key: "requires_user_confirmation", Value: mt.RequiresUserConfirmation}}
	}
	return wirejson.Object{
		{Key: "name", Value: ts.Name}, {Key: "type", Value: "code"}, {Key: "description", Value: ts.Description},
		{Key: "display_name", Value: display}, {Key: "category", Value: ts.Category},
		{Key: "plane", Value: toolsNullable(ts.Plane)}, {Key: "group", Value: toolsNullable(ts.Group)},
		{Key: "requires_user_confirmation", Value: ts.RequiresUserConfirmation},
		{Key: "available_methods", Value: methods}, {Key: "input_schema", Value: wirejson.Object{}},
		{Key: "mcp_instance_id", Value: nil}, {Key: "mcp_instance_name", Value: nil},
	}
}

// toolsTruthy is Python's bool() of a decoded JSON value.
func toolsTruthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case string:
		return x != ""
	case wirejson.Object:
		return len(x) > 0
	case []any:
		return len(x) > 0
	case wirejson.Float:
		return x != 0
	case fmt.Stringer:
		s := strings.TrimLeft(x.String(), "-")
		return strings.Trim(s, "0") != ""
	}
	return true
}

// errToolsMalformed is a persisted tool ToolResponse refuses; Tools skips it.
var errToolsMalformed = errors.New("a persisted MCP tool is not a valid ToolResponse")

// toolsMCPJSON is _mcp_tool_response.
func toolsMCPJSON(tool any, inst ToolsMCPInstance) (wirejson.Object, bool, error) {
	obj, ok := tool.(wirejson.Object)
	if !ok {
		return nil, false, errToolsMalformed
	}
	function := obj
	if f, ok := obj.Get("function"); ok {
		if fo, isObj := f.(wirejson.Object); isObj {
			function = fo
		}
	}
	name, _ := function.Get("name")
	if !toolsTruthy(name) {
		return nil, false, nil
	}
	nameStr, isStr := name.(string)
	if !isStr {
		return nil, false, errToolsMalformed
	}
	desc, _ := function.Get("description")
	if !toolsTruthy(desc) {
		desc = "MCP tool: " + nameStr
	}
	if _, isStr := desc.(string); !isStr {
		return nil, false, errToolsMalformed
	}
	schema, _ := function.Get("parameters")
	if !toolsTruthy(schema) {
		schema, _ = function.Get("inputSchema")
	}
	if !toolsTruthy(schema) {
		schema = wirejson.Object{}
	}
	if _, isObj := schema.(wirejson.Object); !isObj {
		return nil, false, errToolsMalformed
	}
	return wirejson.Object{
		{Key: "name", Value: nameStr}, {Key: "type", Value: "mcp"}, {Key: "description", Value: desc},
		{Key: "display_name", Value: ""}, {Key: "category", Value: ""}, {Key: "plane", Value: nil}, {Key: "group", Value: nil},
		{Key: "requires_user_confirmation", Value: false}, {Key: "available_methods", Value: []any{}},
		{Key: "input_schema", Value: schema}, {Key: "mcp_instance_id", Value: inst.ID}, {Key: "mcp_instance_name", Value: inst.Name},
	}, true, nil
}

// Presets is list_agent_presets.
func (m *Misc) Presets(ctx context.Context, c authn.Caller) (any, error) {
	if m.d.AgentCatalog == nil {
		return nil, &UnwiredError{Feature: "agent presets (catalog)"}
	}
	return m.d.AgentCatalog.PresetsJSON(ctx, c)
}

// Install is install_agent: the fork, the creator's ownership, the agent with its skills.
func (m *Misc) Install(ctx context.Context, c authn.Caller, identifier string) (View, error) {
	if m.d.AgentCatalog == nil {
		return View{}, &UnwiredError{Feature: "installing a catalog agent (catalog)"}
	}
	id, err := m.d.AgentCatalog.Install(ctx, c, identifier)
	if err != nil {
		return View{}, err
	}
	uid, err := uuid.Parse(id)
	if err != nil {
		return View{}, err
	}
	a, ok, err := m.s.load(ctx, c.Workspace, uid, true)
	if err != nil {
		return View{}, err
	}
	if !ok {
		return View{}, domain.ErrAgentNotFound
	}
	if a.CreatedBy == c.UserID {
		if err := m.s.grantOwner(ctx, c, id); err != nil {
			return View{}, err
		}
	}
	v := View{Agent: a, Tools: toolsFromColumn(a.Tools)}
	if m.s.d.A2AAgentURL != "" {
		v.A2AURL = ptr(strings.Replace(strings.TrimRight(m.s.d.A2AAgentURL, "/"), "{agent_id}", a.ID, 1))
	}
	return v, nil
}
