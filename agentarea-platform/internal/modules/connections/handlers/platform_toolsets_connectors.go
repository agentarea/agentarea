package handlers

import (
	"context"
	"encoding/json"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/service"
	identityapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
)

// ConnectorToolsToolset is api.PlatformConnectorTools over the connections service.
type ConnectorToolsToolset struct {
	Svc   *service.Service
	Slugs identityapi.WorkspaceSlugs
}

var _ api.PlatformConnectorTools = ConnectorToolsToolset{}

// names is _names: the connector's id, or its name case-folded.
func names(id, name, connector string) bool {
	return connector == id || strings.EqualFold(connector, name)
}

func verified(inst domain.Instance) bool {
	if inst.VerificationRaw != nil {
		s, _ := inst.VerificationRaw["status"].(string)
		return s == "succeeded"
	}
	return inst.Verification.Status == "succeeded"
}

func (t ConnectorToolsToolset) Searchable(ctx context.Context, c authn.Caller, connector *string) ([]api.Connector, error) {
	readable, err := t.Svc.ReadableIDs(ctx, c)
	if err != nil {
		return nil, err
	}
	instances, err := t.Svc.AllInstances(ctx, c)
	if err != nil {
		return nil, err
	}
	conns, err := t.Svc.AllConnections(ctx, c)
	if err != nil {
		return nil, err
	}
	var out []api.Connector
	for _, inst := range instances {
		if _, ok := readable[inst.ID]; (!ok && !inst.PlatformManaged()) || !verified(inst) ||
			(connector != nil && !names(inst.ID, inst.Name, *connector)) {
			continue
		}
		tools := []api.ConnectorTool{}
		for _, tool := range domain.ToolMaps(inst.Tools) {
			name, _ := tool["name"].(string)
			desc, _ := tool["description"].(string)
			ann, _ := tool["annotations"].(map[string]any)
			title, _ := ann["title"].(string)
			tools = append(tools, api.ConnectorTool{Name: name, Description: desc, Title: title, Hint: domain.ToolSafetyHint(tool), InputSchema: tool["inputSchema"]})
		}
		out = append(out, api.Connector{ID: inst.ID, Name: inst.Name, Tools: tools})
	}
	for _, conn := range conns {
		if _, ok := readable[conn.ID]; (!ok && !conn.PlatformManaged()) || conn.Status != "active" ||
			(connector != nil && !names(conn.ID, conn.Name, *connector)) {
			continue
		}
		hints, err := t.hints(ctx, c, conn)
		if err != nil {
			return nil, err
		}
		tools := []api.ConnectorTool{}
		for _, tool := range conn.AvailableTools {
			var schema any
			if tool.InputSchema != nil {
				schema = tool.InputSchema
			}
			tools = append(tools, api.ConnectorTool{Name: tool.Name, Description: tool.Description, Hint: hints[tool.Name], InputSchema: schema})
		}
		out = append(out, api.Connector{ID: conn.ID, Name: conn.Name, Tools: tools})
	}
	return out, nil
}

// hints reads the connection's stored spec for its operations' safety hints.
func (t ConnectorToolsToolset) hints(ctx context.Context, c authn.Caller, conn domain.Connection) (map[string]string, error) {
	id, err := uuid.Parse(conn.ID)
	if err != nil {
		return nil, err
	}
	full, ok, err := t.Svc.FullConnection(ctx, c, id)
	if err != nil || !ok {
		return map[string]string{}, err
	}
	return t.Svc.OperationHints(ctx, full), nil
}

func (t ConnectorToolsToolset) Call(ctx context.Context, c authn.Caller, connector, tool string, args json.RawMessage, confirm bool) (api.ConnectorCall, error) {
	all, err := t.Svc.AllInstances(ctx, c)
	if err != nil {
		return api.ConnectorCall{}, err
	}
	allConns, err := t.Svc.AllConnections(ctx, c)
	if err != nil {
		return api.ConnectorCall{}, err
	}
	var instances []domain.Instance
	var conns []domain.Connection
	var ids []string
	for _, inst := range all {
		if names(inst.ID, inst.Name, connector) {
			instances = append(instances, inst)
			ids = append(ids, inst.ID)
		}
	}
	for _, conn := range allConns {
		if names(conn.ID, conn.Name, connector) {
			conns = append(conns, conn)
			ids = append(ids, conn.ID)
		}
	}
	switch {
	case len(ids) == 0:
		return api.ConnectorCall{}, api.ErrNoConnector
	case len(ids) > 1:
		return api.ConnectorCall{}, &api.AmbiguousConnectorError{IDs: ids}
	case len(conns) == 1:
		return t.callOpenAPI(ctx, c, conns[0], tool, args, confirm)
	}
	return t.callInstance(ctx, c, instances[0], tool, args, confirm)
}

func (t ConnectorToolsToolset) callInstance(ctx context.Context, c authn.Caller, inst domain.Instance, tool string, args json.RawMessage, confirm bool) (api.ConnectorCall, error) {
	if !inst.PlatformManaged() {
		if err := t.Svc.Require(ctx, c, "use_connection", "mcp_instance", inst.ID); err != nil {
			return api.ConnectorCall{}, toolRefusal(err)
		}
	}
	action, err := t.Svc.InstanceConnectAction(ctx, c, inst, false, slugOf(ctx, t.Slugs, c))
	if err != nil {
		return api.ConnectorCall{}, err
	}
	if action != nil {
		return api.ConnectorCall{ConnectorID: inst.ID, Connector: inst.Name, ActionRequired: action}, nil
	}
	byName := map[string]map[string]any{}
	var toolNames []string
	for _, spec := range domain.ToolMaps(inst.Tools) {
		name, _ := spec["name"].(string)
		if name == "" {
			continue
		}
		if _, seen := byName[name]; !seen {
			toolNames = append(toolNames, name)
		}
		byName[name] = spec
	}
	spec, ok := byName[tool]
	if !ok {
		return api.ConnectorCall{}, &api.UnknownToolError{Connector: inst.Name, Names: toolNames}
	}
	if domain.ToolSafetyHint(spec) == "destructive" && !confirm {
		return api.ConnectorCall{Connector: inst.Name, Tool: tool, ConfirmationRequired: true}, nil
	}
	res, err := t.Svc.CallInstanceTool(ctx, c, inst, tool, args)
	if err != nil {
		return api.ConnectorCall{}, &api.ToolCallFailedError{Connector: inst.Name, Err: err}
	}
	content, _ := res["content"].([]map[string]any)
	isError, _ := res["isError"].(bool)
	return api.ConnectorCall{ConnectorID: inst.ID, Connector: inst.Name, Tool: tool, Content: content,
		StructuredContent: res["structuredContent"], IsError: isError}, nil
}

func (t ConnectorToolsToolset) callOpenAPI(ctx context.Context, c authn.Caller, conn domain.Connection, tool string, args json.RawMessage, confirm bool) (api.ConnectorCall, error) {
	if !conn.PlatformManaged() {
		if err := t.Svc.Require(ctx, c, "use_connection", "openapi_connection", conn.ID); err != nil {
			return api.ConnectorCall{}, toolRefusal(err)
		}
	}
	action, err := t.Svc.ConnectionConnectAction(ctx, c, conn, slugOf(ctx, t.Slugs, c))
	if err != nil {
		return api.ConnectorCall{}, err
	}
	if action != nil {
		return api.ConnectorCall{ConnectorID: conn.ID, Connector: conn.Name, ActionRequired: action}, nil
	}
	var toolNames []string
	known := false
	for _, at := range conn.AvailableTools {
		if at.Name == "" {
			continue
		}
		toolNames = append(toolNames, at.Name)
		known = known || at.Name == tool
	}
	if !known {
		return api.ConnectorCall{}, &api.UnknownToolError{Connector: conn.Name, Names: toolNames}
	}
	hints, err := t.hints(ctx, c, conn)
	if err != nil {
		return api.ConnectorCall{}, err
	}
	if hints[tool] == "destructive" && !confirm {
		return api.ConnectorCall{Connector: conn.Name, Tool: tool, ConfirmationRequired: true}, nil
	}
	res, err := t.Svc.CallOpenAPITool(ctx, c, conn.ID, tool, args)
	if err != nil {
		return api.ConnectorCall{}, &api.ToolCallFailedError{Connector: conn.Name, Err: err}
	}
	return api.ConnectorCall{ConnectorID: conn.ID, Connector: conn.Name, Tool: tool,
		Content: []map[string]any{{"type": "text", "text": res.Text}}, StructuredContent: res.StructuredContent, IsError: res.IsError}, nil
}
