package service

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/openapispec"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/payment"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

// OperationTool is one operation of an OpenAPI connection served as a tool.
type OperationTool struct {
	// Name is _slugify_name(operation name).
	Name        string
	Description string
	InputSchema map[string]any
	// Operation is the stored available_tools name.
	Operation string
}

// ToolResult is a tool call's answer as an MCP result carries it.
type ToolResult struct {
	Text              string
	IsError           bool
	StructuredContent any
}

// callTimeout is the operation call's whole-request deadline.
const callTimeout = 30 * time.Second

func (s *Service) fullConnection(ctx context.Context, ws scope.Workspace, id uuid.UUID) (domain.Connection, bool, error) {
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return domain.Connection{}, false, err
	}
	defer release()
	return s.d.OpenAPIWrites.Full(ctx, sess, id)
}

// connectionOperations is connection_operations: the stored tools by the
// name each is served under, first position kept.
func connectionOperations(conn domain.Connection) []OperationTool {
	var out []OperationTool
	index := map[string]int{}
	for _, t := range conn.AvailableTools {
		if t.Name == "" {
			continue
		}
		schema := t.InputSchema
		if schema == nil {
			schema = map[string]any{"type": "object", "properties": map[string]any{}}
		}
		op := OperationTool{Name: openapispec.Slugify(t.Name), Description: t.Description, InputSchema: schema, Operation: t.Name}
		if i, ok := index[op.Name]; ok {
			out[i] = op
			continue
		}
		index[op.Name] = len(out)
		out = append(out, op)
	}
	return out
}

func (s *Service) callerPolicy(ctx context.Context, c authn.Caller) (governanceapi.Policy, error) {
	if s.d.Policies == nil {
		return governanceapi.Policy{}, &domain.Unavailable{Msg: "tool policies are not available"}
	}
	return s.d.Policies.Effective(ctx, c.Workspace, c.UserID)
}

// ConnectionTools is connection_mcp's list_tools: the connection's
// operations the caller's policy does not deny (one held for approval is offered).
func (s *Service) ConnectionTools(ctx context.Context, c authn.Caller, connectionID string) ([]OperationTool, error) {
	id, err := uuid.Parse(connectionID)
	if err != nil {
		return nil, domain.ErrConnectionNotFound()
	}
	v, err := s.GetConnection(ctx, c, id)
	if err != nil {
		return nil, err
	}
	policy, err := s.callerPolicy(ctx, c)
	if err != nil {
		return nil, err
	}
	conn := v.Connection
	out := []OperationTool{}
	for _, op := range connectionOperations(conn) {
		tool, names := OpenAPIToolNames(conn.ID, conn.Name, op.Operation)
		if d := governanceapi.DecideToolPolicy(&policy, tool, names); d.Action != governanceapi.ToolDeny {
			out = append(out, op)
		}
	}
	return out, nil
}

// CallConnectionTool is call_openapi_tool: one operation of the connection
// run as c, judged by c's policy under OpenAPIToolNames.
func (s *Service) CallConnectionTool(ctx context.Context, c authn.Caller, connectionID, tool string, args json.RawMessage) (ToolResult, error) {
	return s.callConnectionTool(ctx, c, connectionID, tool, args, true)
}

// callConnectionTool runs the operation; judge false is for a caller that
// has judged and audited the call itself.
func (s *Service) callConnectionTool(ctx context.Context, c authn.Caller, connectionID, tool string, args json.RawMessage, judge bool) (ToolResult, error) {
	id, err := uuid.Parse(connectionID)
	if err != nil {
		return ToolResult{}, domain.ErrConnectionNotFound()
	}
	conn, ok, err := s.fullConnection(ctx, c.Workspace, id)
	if err != nil {
		return ToolResult{}, err
	}
	if !ok {
		return ToolResult{}, domain.ErrConnectionNotFound()
	}
	var op *OperationTool
	for _, o := range connectionOperations(conn) {
		if o.Name == tool || o.Operation == tool {
			op = &o
			break
		}
	}
	if op == nil {
		return ToolResult{Text: fmt.Sprintf("%s has no tool %s", conn.Name, tool), IsError: true}, nil
	}
	call := func() (ToolResult, error) {
		return s.runOperation(ctx, c, conn, op.Operation, args)
	}
	if !judge {
		return call()
	}
	policy, err := s.callerPolicy(ctx, c)
	if err != nil {
		return ToolResult{}, err
	}
	name, names := OpenAPIToolNames(conn.ID, conn.Name, op.Operation)
	d := governanceapi.DecideToolPolicy(&policy, name, names)
	audit := toolAudit{resourceType: "openapi_connection", resourceID: conn.ID, actorType: actorOf(c), name: name, args: args}
	held := func() runsapi.HeldCall {
		return heldCall(c, &policy, name, names, "", conn.Name, op.Operation, "", args, d.Reason)
	}
	out, refused, err := s.judged(ctx, c, c.ClientID, audit, d, held, openAPIBinding(conn.ID, op.Operation), func() (any, error) {
		return call()
	})
	if err != nil {
		return ToolResult{}, err
	}
	if refused != "" {
		return ToolResult{Text: refused, IsError: true}, nil
	}
	return out.(ToolResult), nil
}

func (s *Service) runOperation(ctx context.Context, c authn.Caller, conn domain.Connection, operation string, args json.RawMessage) (ToolResult, error) {
	arguments := map[string]any{}
	if len(bytes.TrimSpace(args)) > 0 && string(bytes.TrimSpace(args)) != "null" {
		dec := json.NewDecoder(bytes.NewReader(args))
		dec.UseNumber()
		if err := dec.Decode(&arguments); err != nil {
			return ToolResult{Text: "Invalid arguments: " + err.Error(), IsError: true}, nil
		}
	}
	res := s.callOperation(ctx, c.Workspace, c.UserID, conn, operation, arguments, nil)
	text := res.Result
	if !res.Success {
		text = res.Error
	}
	return ToolResult{Text: text, IsError: !res.Success}, nil
}

// CallOpenAPI implements api.OpenAPITools for runs.
func (s *Service) CallOpenAPI(ctx context.Context, ws scope.Workspace, call api.OpenAPICall) api.OpenAPIResult {
	id, err := uuid.Parse(call.ConnectionID)
	if err != nil {
		return api.OpenAPIResult{Error: "connection not found", ToolName: openapispec.Slugify(call.Operation)}
	}
	conn, ok, err := s.fullConnection(ctx, ws, id)
	if err != nil {
		s.d.Log.ErrorContext(ctx, "could not read an OpenAPI connection", "connection_id", call.ConnectionID, "error", err)
		return api.OpenAPIResult{Error: "Failed to fetch connection: " + err.Error(), ToolName: openapispec.Slugify(call.Operation)}
	}
	if !ok {
		return api.OpenAPIResult{Error: "connection not found", ToolName: openapispec.Slugify(call.Operation)}
	}
	allowed, err := s.agentMayUse(ctx, call.AgentID, "openapi_connection", conn.ID, func() (bool, error) { return conn.PlatformManaged(), nil })
	if err != nil {
		s.d.Log.ErrorContext(ctx, "could not check the agent may use an OpenAPI connection", "connection_id", conn.ID, "error", err)
		return api.OpenAPIResult{Error: "Failed to check the connection's use: " + err.Error(), ToolName: openapispec.Slugify(call.Operation)}
	}
	if !allowed {
		return api.OpenAPIResult{ToolName: openapispec.Slugify(call.Operation), Error: fmt.Sprintf(
			"Agent %s may not call through connection %s: it is someone's personal connection that was not lent to this agent", call.AgentID, conn.ID)}
	}
	pay := s.paying(ws, call.UserID, call.AgentID, openapispec.Slugify(call.Operation), call.ToolCallID, call.Paid)
	return s.callOperation(ctx, ws, call.UserID, conn, call.Operation, call.Args, pay)
}

// checkPlatformURL is validate_url with allow_private: a scheme and a host.
func checkPlatformURL(raw string) error {
	u, err := url.Parse(raw)
	if err != nil || u.Hostname() == "" {
		return &domain.Invalid{Msg: "URL has no hostname."}
	}
	if scheme := strings.ToLower(u.Scheme); scheme != "http" && scheme != "https" {
		return &domain.Invalid{Msg: fmt.Sprintf("URL scheme '%s' is not allowed. Only http and https are permitted.", u.Scheme)}
	}
	return nil
}

// callOperation is OpenAPITool.execute: the operation called with the
// connection's credentials, a success stamped as its last dispatch. pay answers
// the 402s the agent's wallet can pay.
func (s *Service) callOperation(ctx context.Context, ws scope.Workspace, userID string, conn domain.Connection, operation string, args map[string]any, pay *payment.Session) api.OpenAPIResult {
	toolName := openapispec.Slugify(operation)
	fail := func(msg string) api.OpenAPIResult { return api.OpenAPIResult{Error: msg, ToolName: toolName} }
	var op *openapispec.Operation
	if conn.SpecContent != nil {
		ops, err := openapispec.ParseOperations(conn.SpecContent, configuredQuery(conn.CustomQuery))
		if err != nil {
			s.d.Log.ErrorContext(ctx, "could not parse an OpenAPI connection's spec", "connection_id", conn.ID, "error", err)
		}
		for i := range ops {
			if ops[i].Name == operation {
				op = &ops[i]
				break
			}
		}
		if op == nil {
			for i := range ops {
				if openapispec.Slugify(ops[i].Name) == operation {
					op = &ops[i]
					break
				}
			}
		}
	}
	if op == nil {
		return fail(fmt.Sprintf("%s has no operation %s", conn.Name, operation))
	}
	toolName = openapispec.Slugify(op.Name)
	dest := netguard.Member
	if conn.PlatformManaged() {
		dest = netguard.Internal
		if err := checkPlatformURL(conn.BaseURL); err != nil {
			return fail("SSRF validation failed: " + err.Error())
		}
	} else if _, err := s.d.Out.Guard().CheckURL(ctx, conn.BaseURL); err != nil {
		s.d.Log.ErrorContext(ctx, "SSRF validation failed", "connection_id", conn.ID, "error", err)
		return fail("SSRF validation failed: " + openapispec.UnsafeMessage(err))
	}
	headers, err := s.connectionHeaders(ctx, ws, userID, conn)
	if err != nil {
		s.d.Log.ErrorContext(ctx, "could not resolve an OpenAPI connection's headers", "connection_id", conn.ID, "error", err)
		return fail("Failed to resolve headers: " + err.Error())
	}
	base, err := s.connectionBaseURL(ctx, ws, userID, conn)
	if err != nil {
		s.d.Log.ErrorContext(ctx, "could not resolve an OpenAPI connection's base URL", "connection_id", conn.ID, "error", err)
		return fail("Failed to resolve base URL: " + err.Error())
	}
	query, err := s.connectionQuery(ctx, ws, userID, conn)
	if err != nil {
		s.d.Log.ErrorContext(ctx, "could not resolve an OpenAPI connection's query parameters", "connection_id", conn.ID, "error", err)
		return fail("Failed to resolve query parameters: " + err.Error())
	}
	req, urlTemplate, err := openapispec.Build(ctx, openapispec.Request{
		Op: *op, BaseTemplate: conn.BaseURL, BaseURL: base, Headers: headers, Query: query, Args: args,
	})
	if err != nil {
		return fail(err.Error())
	}
	client := &http.Client{
		Transport:     pay.Wrap(s.d.Out.Transport(dest)),
		Timeout:       callTimeout,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
	res := openapispec.Do(client, req, *op)
	if !res.Success && res.StatusCode == 0 {
		s.d.Log.WarnContext(ctx, "OpenAPI call failed", "method", op.Method, "url", urlTemplate, "error", res.Error)
	}
	if res.Success {
		s.recordOpenAPIDispatch(ctx, ws, conn.ID)
	}
	payments := pay.Payments()
	if n := len(payments); !res.Success && n > 0 && payments[n-1].Error != "" {
		res.Error += "; payment error: " + payments[n-1].Error
	}
	return api.OpenAPIResult{Success: res.Success, Result: res.Result, Error: res.Error, StatusCode: res.StatusCode, Body: res.Body, ToolName: toolName,
		Payments: payments}
}

// pyISO is datetime.now(UTC).isoformat().
func pyISO(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/1000 == 0 {
		return t.Format("2006-01-02T15:04:05") + "+00:00"
	}
	return t.Format("2006-01-02T15:04:05.000000") + "+00:00"
}

// recordOpenAPIDispatch is record_dispatch: the call already happened, so a failed
// write is logged and never fails it.
func (s *Service) recordOpenAPIDispatch(ctx context.Context, ws scope.Workspace, connectionID string) {
	id, err := uuid.Parse(connectionID)
	if err != nil {
		return
	}
	dispatch := map[string]any{"status": "succeeded", "at": pyISO(s.d.Now()), "error": nil}
	err = s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		_, err := s.d.OpenAPIWrites.SetLastDispatch(ctx, sess, id, dispatch)
		return err
	})
	if err != nil {
		s.d.Log.ErrorContext(ctx, "Failed to record the last call of OpenAPI connection", "connection_id", connectionID, "error", err)
	}
}
