package service

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

// UseHeldCalls sets runs' approval gate of held calls; runs is built after connections.
func (s *Service) UseHeldCalls(h runsapi.HeldCalls) { s.d.HeldCalls = h }

// toolAudit is where one tool call's verdict is filed: the resource it went through.
type toolAudit struct {
	resourceType, resourceID, actorType, name string
	args                                      json.RawMessage
	extra                                     map[string]any
}

func actorOf(c authn.Caller) string {
	if c.ClientID != "" {
		return "client"
	}
	return "user"
}

// heldCall is _held_call: the exact call a person is asked to approve, with the approvers the
// policy names.
func heldCall(c authn.Caller, p *governanceapi.Policy, name string, names governanceapi.ToolNames, instanceID, connector, raw, clientName string, args json.RawMessage, reason string) runsapi.HeldCall {
	arguments := map[string]any{}
	if len(args) > 0 && string(args) != "null" {
		_ = decodeUseNumber(args, &arguments)
	}
	call := runsapi.HeldCall{
		UserID: c.UserID, MCPInstanceID: instanceID, Connector: connector, Tool: raw, PolicyName: name,
		Arguments: arguments, Reason: reason,
		Approvers: governanceapi.ApproversForTool(p, name, append(append([]string{}, names.Aliases...), names.Restricting...)),
	}
	if c.ClientID != "" {
		id := c.ClientID
		call.ClientID = &id
		if clientName != "" {
			call.ClientName = &clientName
		}
	}
	return call
}

// gateHeld is _gate_held_call: a held call passed through its approval. run is true when an
// approval lets it run; otherwise text answers the caller as an error. The approval is consumed
// and the verdict audited in one transaction, so an approval is spent only by a call on record.
func (s *Service) gateHeld(ctx context.Context, c authn.Caller, a toolAudit, d governanceapi.ToolDecision, call runsapi.HeldCall) (bool, string, error) {
	if s.d.HeldCalls == nil {
		d = governanceapi.ToolDecision{Action: governanceapi.ToolDeny, Reason: d.Reason + "; approval of a held call is not served by this process"}
		if err := s.auditToolCall(ctx, c, a.resourceType, a.resourceID, a.actorType, a.name, a.args, d, a.extra); err != nil {
			return false, "", err
		}
		return false, "Tool call refused: " + d.Reason, nil
	}
	var out runsapi.HeldOutcome
	err := s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, tx db.Session) error {
		var err error
		if out, err = s.d.HeldCalls.Gate(ctx, tx, c.Workspace, call); err != nil {
			return err
		}
		verdict := d
		switch out.Verdict {
		case runsapi.HeldRun:
			verdict = governanceapi.ToolDecision{Action: governanceapi.ToolAllow,
				Reason: fmt.Sprintf("approved by %s (approval %s)", out.DecidedBy, out.ApprovalID)}
		case runsapi.HeldRejected:
			verdict = governanceapi.ToolDecision{Action: governanceapi.ToolDeny,
				Reason: fmt.Sprintf("rejected by %s (approval %s)", out.DecidedBy, out.ApprovalID)}
		}
		extra := map[string]any{"approval_id": out.ApprovalID}
		for k, v := range a.extra {
			extra[k] = v
		}
		return s.recordToolCall(ctx, tx, c, a.resourceType, a.resourceID, a.actorType, a.name, a.args, verdict, extra)
	})
	if err != nil {
		return false, "", err
	}
	switch out.Verdict {
	case runsapi.HeldRun:
		return true, "", nil
	case runsapi.HeldRejected:
		comment := ""
		if out.Comment != nil && *out.Comment != "" {
			comment = " (" + *out.Comment + ")"
		}
		return false, "Tool call refused: the user rejected this call" + comment + ". Change the arguments to ask again.", nil
	}
	return false, fmt.Sprintf("The workspace policy requires approval to run %s on %s. Ask the user to open the link "+
		"and approve; then call again with the same arguments: %s", out.Tool, out.Connector, out.URL), nil
}

// UseClientCalls sets runs' pricing, caps and metering of calls outside a run.
func (s *Service) UseClientCalls(c runsapi.ClientToolCalls) { s.d.ClientCalls = c }

// judged is _layered_call past the PDP: a held call goes through its approval, an allowed one
// through runs' layer (its price, a hold on the platform's key, the spend caps), each verdict
// audited before anything runs. refused is the text a call that did not run answers with.
func (s *Service) judged(ctx context.Context, c authn.Caller, clientID string, a toolAudit, d governanceapi.ToolDecision,
	held func() runsapi.HeldCall, b runsapi.ToolBinding, run func() (any, error)) (out any, refused string, err error) {
	approved := false
	switch {
	case d.Action == governanceapi.ToolRequireApproval:
		ok, text, err := s.gateHeld(ctx, c, a, d, held())
		if err != nil || !ok {
			return nil, text, err
		}
		approved = true
	case !d.Allowed():
		if err := s.auditToolCall(ctx, c, a.resourceType, a.resourceID, a.actorType, a.name, a.args, d, a.extra); err != nil {
			return nil, "", err
		}
		return nil, "Tool call refused: " + d.Reason, nil
	}
	audit := func(ctx context.Context, refusal string) error {
		if refusal != "" {
			return s.auditToolCall(ctx, c, a.resourceType, a.resourceID, a.actorType, a.name, a.args,
				governanceapi.ToolDecision{Action: governanceapi.ToolDeny, Reason: refusal}, a.extra)
		}
		if approved {
			return nil
		}
		return s.auditToolCall(ctx, c, a.resourceType, a.resourceID, a.actorType, a.name, a.args, d, a.extra)
	}
	if s.d.ClientCalls == nil {
		if err := audit(ctx, ""); err != nil {
			return nil, "", err
		}
		out, err = run()
		return out, "", err
	}
	arguments := map[string]any{}
	if len(a.args) > 0 && string(a.args) != "null" {
		_ = decodeUseNumber(a.args, &arguments)
	}
	refusal, err := s.d.ClientCalls.RunClientCall(ctx, c.Workspace, runsapi.ClientToolCall{
		UserID: c.UserID, ClientID: clientID, ToolName: a.name, Args: arguments, Binding: b,
	}, runsapi.ClientCallHooks{
		Audit: audit,
		Invoke: func(context.Context) (runsapi.ClientToolAnswer, error) {
			v, err := run()
			if err != nil {
				return runsapi.ClientToolAnswer{}, err
			}
			out = v
			return answerOf(v)
		},
	})
	if err != nil {
		return nil, "", err
	}
	if refusal != "" {
		return nil, "Tool call refused: " + refusal, nil
	}
	return out, "", nil
}

// answerOf is _call_outcome: whether the call answered without error, its structured content
// and its _meta.
func answerOf(v any) (runsapi.ClientToolAnswer, error) {
	switch r := v.(type) {
	case ToolResult:
		return runsapi.ClientToolAnswer{Success: !r.IsError, Body: r.StructuredContent}, nil
	case map[string]any:
		isError, _ := r["isError"].(bool)
		meta, _ := r["_meta"].(map[string]any)
		return runsapi.ClientToolAnswer{Success: !isError, Body: r["structuredContent"], Meta: meta}, nil
	}
	raw, err := json.Marshal(v)
	if err != nil {
		return runsapi.ClientToolAnswer{}, err
	}
	var m map[string]any
	if err := decodeUseNumber(raw, &m); err != nil {
		return runsapi.ClientToolAnswer{}, err
	}
	return answerOf(m)
}

func mcpBinding(instanceID, raw string) runsapi.ToolBinding {
	return runsapi.ToolBinding{Source: "mcp", MCP: &runsapi.MCPBinding{InstanceID: instanceID, RawName: raw}}
}

func openAPIBinding(connectionID, operation string) runsapi.ToolBinding {
	return runsapi.ToolBinding{Source: "openapi", OpenAPI: &runsapi.OpenAPIBinding{ConnectionID: connectionID, OperationID: operation}}
}
