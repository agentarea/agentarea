package service

import (
	"context"
	"encoding/json"
	"net/http"
	"slices"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/mcpserver"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/toolname"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
)

func errProxyNotFound() error { return &domain.NotFound{Msg: "MCP instance not found"} }

// LocateConnection is bind_mcp_instance_workspace: the workspace of the MCP
// instance (first) or API connection the proxy URL names, which p must reach.
// A malformed, unknown or foreign id is "MCP instance not found".
func (s *Service) LocateConnection(ctx context.Context, p authn.Principal, raw string) (uuid.UUID, string, error) {
	id, err := uuid.Parse(raw)
	if err != nil {
		return uuid.Nil, "", errProxyNotFound()
	}
	q, release, err := s.d.DB.Global().Read(ctx)
	if err != nil {
		return uuid.Nil, "", err
	}
	defer release()
	owners, err := s.d.Instances.ConnectionOwners(ctx, q, id)
	if err != nil {
		return uuid.Nil, "", err
	}
	if len(owners) == 0 || !slices.Contains(p.AccessibleWorkspaces, owners[0].WorkspaceID) {
		return uuid.Nil, "", errProxyNotFound()
	}
	return id, owners[0].WorkspaceID, nil
}

// ProxyTarget is the MCP instance the proxy serves; isOpenAPI when the id
// names an API connection of c's workspace instead.
func (s *Service) ProxyTarget(ctx context.Context, c authn.Caller, id uuid.UUID) (inst domain.Instance, isOpenAPI bool, err error) {
	err = s.read(ctx, c, func(sess db.Session) error {
		var ok bool
		inst, ok, err = s.d.Instances.Get(ctx, sess, id)
		if err != nil || ok {
			return err
		}
		_, ok, err = s.d.Connections.Get(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return errProxyNotFound()
		}
		isOpenAPI = true
		return nil
	})
	return inst, isOpenAPI, err
}

// ProxyRefusal is a proxied request refused before it reaches the upstream:
// Body set is a JSON-RPC error body (header mismatch), else Detail.
type ProxyRefusal struct {
	Status int
	Detail string
	Body   any
}

func (e *ProxyRefusal) Error() string { return e.Detail }

// eventNameBearing is the params key Mcp-Name mirrors for an MCP Events method.
func eventNameBearing(method string) string {
	switch method {
	case "events/poll", "events/stream", "events/subscribe", "events/unsubscribe":
		return "name"
	}
	return ""
}

// refusedEventMethod is a subscription only a stream's MCP Events source makes.
func refusedEventMethod(method string) bool {
	return method == "events/subscribe" || method == "events/unsubscribe"
}

// governedEventMethod is an events read judged like a tool call.
func governedEventMethod(method string) bool {
	return method == "events/list" || method == "events/poll"
}

// SingleToolCall is _single_tool_call: the tool a body calls when it is
// exactly one tools/call.
func SingleToolCall(body []byte) string {
	payload, ok := decodeJSON(body)
	if !ok {
		return ""
	}
	calls := toolCalls(payload)
	if len(calls) == 1 {
		return calls[0]
	}
	return ""
}

func decodeJSON(body []byte) (any, bool) {
	if len(body) == 0 {
		return nil, false
	}
	var payload any
	if json.Unmarshal(body, &payload) != nil {
		return nil, false
	}
	return payload, true
}

func messages(payload any) []map[string]any {
	list, isList := payload.([]any)
	if !isList {
		list = []any{payload}
	}
	var out []map[string]any
	for _, m := range list {
		if mm, ok := m.(map[string]any); ok {
			out = append(out, mm)
		}
	}
	return out
}

func toolCalls(payload any) []string {
	var names []string
	for _, m := range messages(payload) {
		if m["method"] != "tools/call" {
			continue
		}
		params, _ := m["params"].(map[string]any)
		if name, ok := params["name"].(string); ok && name != "" {
			names = append(names, name)
		}
	}
	return names
}

// JudgeProxyRequest is _authorize_mcp_tool_calls: the routing headers held
// to the body, events subscriptions refused, and every tools/call (and
// events/list, events/poll) judged by c's workspace+user policy under
// mcp:<instance>:<tool>. A body that is not JSON passes unjudged.
func (s *Service) JudgeProxyRequest(ctx context.Context, c authn.Caller, instanceID string, body []byte, h http.Header) error {
	payload, ok := decodeJSON(body)
	if !ok {
		return nil
	}
	if err := headerConsistency(payload, h); err != nil {
		return err
	}
	var judged []string
	for _, m := range messages(payload) {
		method, _ := m["method"].(string)
		if refusedEventMethod(method) {
			return &ProxyRefusal{Status: http.StatusForbidden, Detail: method + " is refused through the proxy: only a stream's MCP Events source subscribes to an MCP server's events"}
		}
	}
	judged = append(judged, toolCalls(payload)...)
	for _, m := range messages(payload) {
		if method, _ := m["method"].(string); governedEventMethod(method) {
			judged = append(judged, method)
		}
	}
	if len(judged) == 0 {
		return nil
	}
	policy, err := s.d.Policies.Effective(ctx, c.Workspace, c.UserID)
	if err != nil {
		return err
	}
	for _, tool := range judged {
		d := governanceapi.DecideToolPolicy(&policy, toolname.MCPToolTarget(instanceID, tool), governanceapi.ToolNames{Restricting: []string{tool}, NameAllows: true})
		if !d.Allowed() {
			return &ProxyRefusal{Status: http.StatusForbidden, Detail: "Tool call denied: " + tool + ": " + d.Reason}
		}
	}
	return nil
}

func mismatch(id any, msg string) error {
	return &ProxyRefusal{Status: http.StatusBadRequest, Detail: msg, Body: map[string]any{
		"jsonrpc": "2.0", "id": id, "error": map[string]any{"code": mcpserver.CodeHeaderMismatch, "message": msg},
	}}
}

func headerValue(h http.Header, name string) (string, bool) {
	v := h.Values(name)
	if len(v) == 0 {
		return "", false
	}
	return v[0], true
}

func pyRepr(v any) string {
	switch t := v.(type) {
	case nil:
		return "None"
	case string:
		return "'" + t + "'"
	}
	raw, _ := json.Marshal(v)
	return string(raw)
}

// headerConsistency is _validate_mcp_header_consistency.
func headerConsistency(payload any, h http.Header) error {
	methodHeader, hasMethod := headerValue(h, mcpserver.HeaderMethod)
	nameHeader, hasName := headerValue(h, mcpserver.HeaderName)
	if !hasMethod && !hasName {
		return nil
	}
	if _, isList := payload.([]any); isList {
		return mismatch(nil, "Header mismatch: Mcp-Method and Mcp-Name headers cannot be validated against a JSON-RPC batch body")
	}
	m, ok := payload.(map[string]any)
	if !ok {
		return mismatch(nil, "Header mismatch: routing headers require a JSON-RPC request object")
	}
	id := m["id"]
	bodyMethod := m["method"]
	if hasMethod && methodHeader != bodyMethod {
		return mismatch(id, "Header mismatch: Mcp-Method header value "+pyRepr(methodHeader)+" does not match body value "+pyRepr(bodyMethod))
	}
	if !hasName {
		return nil
	}
	key := ""
	if method, ok := bodyMethod.(string); ok {
		key, _ = mcpserver.NameBearingParam(method)
		if key == "" {
			key = eventNameBearing(method)
		}
	}
	if key == "" {
		return mismatch(id, "Header mismatch: Mcp-Name header is not defined for request method "+pyRepr(bodyMethod))
	}
	params, _ := m["params"].(map[string]any)
	bodyName := params[key]
	decoded, ok := mcpserver.DecodeHeaderValue(nameHeader)
	if !ok || decoded != bodyName {
		return mismatch(id, "Header mismatch: Mcp-Name header value "+pyRepr(nameHeader)+" does not match body value "+pyRepr(bodyName))
	}
	return nil
}
