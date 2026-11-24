package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/mcpclient"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/payment"
)

// Tool call limits (tool_timeout.py, service.py).
const (
	DefaultToolTimeout       = 300 * time.Second
	toolTimeoutGrace         = 30 * time.Second
	StructuredContentMaxChar = 16_000
)

// MCPTools is the run-time call path other modules use (api.MCPTools).
func (s *Service) MCPTools() api.MCPTools { return mcpTools{s} }

type mcpTools struct{ s *Service }

func (t mcpTools) Call(ctx context.Context, call api.MCPCall) (api.MCPResult, error) {
	ws, err := scope.NewWorkspace(call.WorkspaceID, "")
	if err != nil {
		return api.MCPResult{}, err
	}
	if res, refused, err := t.s.refuseUnusable(ctx, ws, call); err != nil || refused {
		return res, err
	}
	return t.s.ExecuteTool(ctx, ws, call)
}

// refuseUnusable is the call-time use_connection check on the instance the
// binding names: the agent's own right, or the run's user's for an instance
// selected for the run; a platform instance needs neither. A missing
// instance is ExecuteTool's to answer.
func (s *Service) refuseUnusable(ctx context.Context, ws scope.Workspace, call api.MCPCall) (api.MCPResult, bool, error) {
	id, err := uuid.Parse(call.InstanceID)
	if err != nil {
		return api.MCPResult{}, false, nil
	}
	inst, err := s.instanceIn(ctx, ws, id)
	var nf *domain.NotFound
	if errors.As(err, &nf) {
		return api.MCPResult{}, false, nil
	}
	if err != nil {
		return api.MCPResult{}, false, err
	}
	allowed, err := s.agentMayUse(ctx, call.AgentID, "mcp_instance", inst.ID, func() (bool, error) {
		if call.UserID != "" {
			ok, err := s.perms.Check(ctx, "User:"+call.UserID, "use_connection", "mcp_instance", inst.ID)
			if err != nil || ok {
				return ok, err
			}
		}
		return inst.PlatformManaged(), nil
	})
	if err != nil || allowed {
		return api.MCPResult{}, false, err
	}
	msg := fmt.Sprintf("Agent %s may not call through connection %s: it is someone's personal connection that was not lent to this agent",
		call.AgentID, inst.ID)
	return api.MCPResult{Result: msg, Error: msg, ToolName: call.Tool, ServerInstanceID: inst.ID}, true, nil
}

// toolTimeout is the instance's tool_timeout_seconds, 300 by default.
func toolTimeout(spec map[string]any) (time.Duration, error) {
	if msg := domain.ToolTimeoutError(spec); msg != "" {
		return 0, errors.New(msg)
	}
	v, ok := spec[domain.ToolTimeoutKey]
	if !ok {
		return DefaultToolTimeout, nil
	}
	var f float64
	switch n := v.(type) {
	case json.Number:
		f, _ = n.Float64()
	case float64:
		f = n
	case int:
		f = float64(n)
	case int64:
		f = float64(n)
	}
	return time.Duration(f * float64(time.Second)), nil
}

// cappedStructured is structuredContent as the event carries it, dropped
// past 16,000 characters of JSON.
func cappedStructured(v any) (any, bool) {
	if v == nil {
		return nil, false
	}
	raw, err := json.Marshal(v)
	if err != nil || len([]rune(string(raw))) > StructuredContentMaxChar {
		return nil, true
	}
	return v, false
}

// callContext is call_context_from_task: the run form of the context, nil outside a task.
func callContext(call api.MCPCall) *CallerContext {
	if call.TaskID == "" || call.ToolCallID == "" {
		return nil
	}
	cc := &CallerContext{TaskID: call.TaskID, ToolCallID: call.ToolCallID, AgentID: call.AgentID}
	if v, ok := call.TaskMetadata["end_user_id"].(string); ok {
		cc.EndUserID = v
	}
	if m, ok := call.TaskMetadata["app_metadata"].(map[string]any); ok {
		cc.Metadata = m
	}
	return cc
}

// ExecuteTool is execute_tool: a bundle routes to its member; the call's
// failures are a result with Success false, stamped on last_dispatch.
func (s *Service) ExecuteTool(ctx context.Context, ws scope.Workspace, call api.MCPCall) (api.MCPResult, error) {
	tool := call.Tool
	var pay *payment.Session
	fail := func(result, msg string) (api.MCPResult, error) {
		s.stampDispatch(call.InstanceID, &msg)
		return api.MCPResult{Result: result, Error: msg, ToolName: tool, ServerInstanceID: call.InstanceID, Payments: pay.Payments()}, nil
	}
	id, err := uuid.Parse(call.InstanceID)
	var inst domain.Instance
	found := false
	if err == nil {
		inst, err = s.instanceIn(ctx, ws, id)
		found = err == nil
		var nf *domain.NotFound
		if err != nil && !errors.As(err, &nf) {
			return api.MCPResult{}, err
		}
	}
	if !found {
		return fail(fmt.Sprintf("MCP server instance %s not found. It may have been deleted.", call.InstanceID),
			fmt.Sprintf("MCP server instance %s not found", call.InstanceID))
	}
	if inst.Transport == domain.TransportBundle {
		return s.executeInBundle(ctx, ws, inst, call, fail)
	}
	spec, ok, err := s.serverSpec(ctx, ws, inst)
	if err != nil {
		return api.MCPResult{}, err
	}
	if !ok {
		reason := fmt.Sprintf("MCP server spec %s not found", inst.ServerSpecID)
		return fail(fmt.Sprintf("MCP '%s' is not available (cannot resolve URL: %s). Re-verify the instance.", inst.Name, reason), reason)
	}
	merged := transportSpec(spec, inst)
	opts, callHeaders, meta, timeout, err := s.callSetup(ctx, ws, inst, merged, call)
	if err != nil {
		return fail(fmt.Sprintf("MCP '%s' is not available (cannot resolve URL: %v). Re-verify the instance.", inst.Name, err), err.Error())
	}
	pay = s.paying(ws, call.UserID, call.AgentID, tool, call.ToolCallID, call.Paid)
	opts.RoundTripper = pay.Wrap(opts.RoundTripper)
	s.d.Log.Info("MCP tool call", "url", opts.URL, "instance_id", inst.ID, "tool", tool)
	res, err := s.callOnce(ctx, opts, mcpclient.Call{Name: tool, Arguments: call.Args, Meta: meta,
		Headers: callHeaders, Timeout: timeout, Progress: progressOf(call)})
	if err != nil {
		s.d.Log.Error("MCP tool call failed", "instance_id", inst.ID, "tool", tool, "error", err)
		if mcpclient.IsTimeout(err) {
			reason := "no result within " + strconv.FormatFloat(timeout.Seconds(), 'g', -1, 64) + " s"
			return fail(fmt.Sprintf("MCP '%s' tool call timed out: %s. The instance's %s (at most %d) sets how long a call may take.",
				inst.Name, reason, domain.ToolTimeoutKey, domain.MaxToolTimeoutSeconds), "MCP tool call timed out: "+reason)
		}
		reason := err.Error()
		if inst.Transport == domain.TransportURL && !answeredInMCP(err) {
			reason = "could not connect to the MCP server"
		}
		return fail(fmt.Sprintf("MCP '%s' tool call failed: %s. Re-verify the instance if this persists.", inst.Name, reason),
			"MCP tool call failed: "+reason)
	}
	text, images := mcpclient.SplitContent(res.Content)
	if text == "" && res.StructuredContent != nil {
		raw, _ := json.Marshal(res.StructuredContent)
		text = string(raw)
	}
	if res.IsError {
		if text == "" {
			text = "MCP tool returned error"
		}
		return fail(text, text)
	}
	s.stampDispatch(inst.ID, nil)
	structured, dropped := cappedStructured(res.StructuredContent)
	out := api.MCPResult{Success: true, Result: text, ToolName: tool, ServerInstanceID: inst.ID, Meta: res.Meta,
		StructuredContent: structured, StructuredContentDropped: dropped, Payments: pay.Payments()}
	for _, im := range images {
		out.Images = append(out.Images, api.MCPImage{MimeType: im.MimeType, Data: im.Data})
	}
	return out, nil
}

func answeredInMCP(err error) bool {
	var rpc *mcpclient.RPCError
	var un *mcpclient.UnauthorizedError
	return errors.As(err, &rpc) || errors.As(err, &un)
}

func progressOf(call api.MCPCall) func(mcpclient.Progress) {
	if call.Progress == nil {
		return nil
	}
	return func(p mcpclient.Progress) { call.Progress(p.Progress, p.Total, p.Message) }
}

// callSetup resolves the endpoint, the connection's headers, the call's
// signed context and _meta, and the timeout.
func (s *Service) callSetup(ctx context.Context, ws scope.Workspace, inst domain.Instance, merged map[string]any, call api.MCPCall) (mcpclient.Options, http.Header, map[string]any, time.Duration, error) {
	var o mcpclient.Options
	t, err := s.targetOf(inst, merged)
	if err != nil {
		return o, nil, nil, 0, err
	}
	if t.url == "" {
		return o, nil, nil, 0, &domain.Invalid{Msg: fmt.Sprintf("Instance %s has no endpoint URL (missing url/external_url in json_spec)", inst.ID)}
	}
	timeout, err := toolTimeout(merged)
	if err != nil {
		return o, nil, nil, 0, err
	}
	h := http.Header{}
	for k, v := range plainHeaders(merged) {
		h.Set(k, v)
	}
	own, err := s.secretHeaders(ctx, ws, inst)
	if err != nil {
		return o, nil, nil, 0, err
	}
	for k, v := range own {
		h.Set(k, v)
	}
	auth, err := s.authHeaders(ctx, ws, inst, t.url, false)
	var inv *domain.Invalid
	if errors.As(err, &inv) {
		return o, nil, nil, 0, err
	}
	for k, v := range auth {
		h.Set(k, v)
	}
	var callHeaders http.Header
	var meta map[string]any
	if cc := callContext(call); cc != nil {
		callHeaders, err = s.contextHeader(ctx, ws, inst, merged, *cc, call.Tool)
		if err != nil {
			return o, nil, nil, 0, err
		}
		if callHeaders != nil {
			meta = contextMeta(ws.ID(), *cc)
		}
	}
	o = mcpclient.Options{URL: t.url, Transport: t.declared, RoundTripper: t.transport, Headers: h,
		ReadTimeout: timeout + toolTimeoutGrace, Verdicts: s.d.Verdicts, VerdictKey: mcpclient.VerdictKey(inst.ID, merged)}
	return o, callHeaders, meta, timeout, nil
}

// callOnce connects and runs one call on its own connection; a server that
// contradicts the cached era gets the call once more after renegotiating.
func (s *Service) callOnce(ctx context.Context, o mcpclient.Options, call mcpclient.Call) (*mcpclient.CallResult, error) {
	c, err := mcpclient.Connect(ctx, o)
	if err != nil {
		return nil, err
	}
	defer c.Close()
	return c.CallTool(ctx, call)
}

func (s *Service) executeInBundle(ctx context.Context, ws scope.Workspace, bundle domain.Instance, call api.MCPCall,
	fail func(string, string) (api.MCPResult, error)) (api.MCPResult, error) {
	var matched map[string]any
	for _, t := range bundle.AvailableTools() {
		if m, ok := t.(map[string]any); ok && m["name"] == call.Tool {
			matched = m
			break
		}
	}
	if matched == nil {
		return fail(fmt.Sprintf("Bundle '%s' does not expose tool '%s'. Try re-verifying the bundle to refresh the tool list.", bundle.Name, call.Tool),
			fmt.Sprintf("Tool '%s' not found in bundle '%s'", call.Tool, bundle.Name))
	}
	member, _ := matched["member_instance_id"].(string)
	original, _ := matched["original_tool_name"].(string)
	if original == "" {
		original = call.Tool
	}
	if member == "" {
		return fail(fmt.Sprintf("Bundle entry for '%s' is missing member_instance_id. Re-verify the bundle to rebuild the tool index.", call.Tool),
			fmt.Sprintf("Bundle entry for '%s' is missing member_instance_id", call.Tool))
	}
	id, err := uuid.Parse(member)
	if err == nil {
		_, err = s.instanceIn(ctx, ws, id)
	}
	if err != nil {
		var nf *domain.NotFound
		if !errors.As(err, &nf) && id != uuid.Nil {
			return api.MCPResult{}, err
		}
		return fail(fmt.Sprintf("Bundle member for tool '%s' (id=%s) not found. Recreate or re-verify the bundle.", call.Tool, member),
			fmt.Sprintf("Bundle member %s not found", member))
	}
	next := call
	next.InstanceID, next.Tool = id.String(), original
	return s.ExecuteTool(ctx, ws, next)
}
