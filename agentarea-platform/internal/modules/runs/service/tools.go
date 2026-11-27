package service

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
)

const (
	payerPlatform = "platform"
	payerPerCall  = "per_call"
	sourceRate    = "rate"
	sourceReport  = "reported"
	settleVendor  = "vendor"
	walletCurr    = "USD"
	// toolProgressInterval: at most two progress events a second per call; completion always goes out.
	toolProgressInterval = 500 * time.Millisecond
)

// toolCallEvents is the namespace of a tool call's ledger keys (costs.py _TOOL_CALL_EVENTS).
const toolCallEvents = "6f1d3c52-9a47-5e0b-8c21-4b7a9e2f1d08"

// ToolCall is one tool call of a run (tools.py execute_mcp_tool_activity).
type ToolCall struct {
	TaskID, ExecutionID, ToolCallID, ToolName string
	Args                                      map[string]any
	Binding                                   api.ToolBinding
	Policy                                    api.Policy
	RunMetadata                               map[string]any
	PolicyApprovalGranted                     bool
	// WorkflowID, RunID and ActivityID identify the attempt; Attempt > 1 is a retry.
	WorkflowID, RunID, ActivityID string
	Attempt                       int
	Heartbeat                     func()
	// ClientID is the registered client a call outside a run came from.
	ClientID string
}

// ToolResult is the tool's answer with what it cost the run.
type ToolResult struct {
	Out         ToolOutput
	Images      []domain.ImageRef
	Cost        money.Decimal
	Payer       string
	CostMetered bool
	Replayed    bool
	Attempt     *int
}

// connection is the connection a call runs on and its declared cost.
type connection struct {
	id, connector, tool, ref, payer string
	cost                            *api.ToolCost
}

func connectionOf(b api.ToolBinding) *connection {
	c := &connection{}
	switch {
	case b.Source == "mcp" && b.MCP != nil:
		c.id, c.tool, c.ref = b.MCP.InstanceID, b.MCP.RawName, "mcp:"+b.MCP.InstanceID
	case b.Source == "openapi" && b.OpenAPI != nil:
		c.id, c.tool, c.ref = b.OpenAPI.ConnectionID, b.OpenAPI.OperationID, "openapi:"+b.OpenAPI.ConnectionID
	default:
		return nil
	}
	c.payer = "workspace"
	if b.Cost != nil {
		c.cost, c.connector = b.Cost, b.Cost.Connector
		if b.Cost.Payer != "" {
			c.payer = b.Cost.Payer
		}
	}
	return c
}

// callConnection is _tool_connection: the connection the call runs on with what its connector
// declares the tool costs now, or why the call cannot be priced.
func (s *Service) callConnection(ctx context.Context, ws scope.Workspace, in ToolCall) (*connection, string, error) {
	conn := connectionOf(in.Binding)
	if conn == nil || in.Binding.Cost != nil || s.d.ToolCosts == nil {
		return conn, "", nil
	}
	cost, err := s.d.ToolCosts.ToolCost(ctx, ws, in.Binding)
	var bad *api.CostDeclarationError
	if errors.As(err, &bad) {
		return nil, "the cost of this call cannot be known: " + bad.Msg, nil
	}
	if err != nil {
		return nil, "", err
	}
	if cost != nil {
		conn.cost, conn.connector, conn.payer = cost, cost.Connector, cost.Payer
	}
	return conn, "", nil
}

func toolNamesOf(b api.ToolBinding) domain.ToolNames {
	if b.Source == "code" || b.Source == "" {
		return domain.ToolNames{NameAllows: true, Restricting: b.RestrictingNames}
	}
	return domain.ToolNames{Aliases: b.PolicyNames, Restricting: b.RestrictingNames}
}

func callRef(in ToolCall) string {
	if in.TaskID != "" && in.ToolCallID != "" {
		return in.TaskID + ":" + in.ToolCallID
	}
	if in.TaskID == "" && in.WorkflowID == "" && in.ToolCallID != "" {
		return in.ToolCallID
	}
	return in.WorkflowID + ":" + in.RunID + ":" + in.ActivityID
}

func deniedResult(reason string) ToolResult {
	return ToolResult{Out: ToolOutput{Result: "Tool call denied by policy: " + reason, Error: reason}}
}

// usage is one metered line of a call.
type usage struct {
	lineKey, payer, source, unit string
	quantity, vendorCost, amount money.Decimal
	vendorCurrency, currency     string
	estimate                     bool
	evidence                     map[string]any
}

// before is what the layer knew before the call: its cost as converted, and any hold.
type before struct {
	model       *costModel
	cost        *meteredCost
	amount      money.Decimal
	currency    string
	converted   bool
	pending     bool
	holdID      string
	heldAmount  money.Decimal
	heldCurrent string
}

// ExecuteTool runs one call through the tool-call layer (governance tool_calls.py):
// policy verdict, the cost known before it, a hold on the platform's key, the
// spend gate, the call, the meter. A refusal is audited and answered, not raised.
func (s *Service) ExecuteTool(ctx context.Context, p Principal, in ToolCall) (ToolResult, error) {
	call := s.d.ToolMetrics.begin(ctx, toolKind(in.Binding), toolPathWorker)
	res, err := s.executeTool(ctx, p, in, call)
	call.end(ctx, err)
	return res, err
}

func (s *Service) executeTool(ctx context.Context, p Principal, in ToolCall, call *toolCall) (ToolResult, error) {
	ws, err := workspace(p)
	if err != nil {
		return ToolResult{}, err
	}
	action, reason := domain.ToolAllow, ""
	if !domain.IsReadFile(in.ToolName, in.Binding) {
		action, reason = domain.DecideToolPolicy(in.Policy, in.ToolName, toolNamesOf(in.Binding))
	}
	switch {
	case action == domain.ToolDeny:
		call.set(toolOutcomeDenied)
		return s.auditedDenial(ctx, p, in, reason)
	case action == domain.ToolRequireApproval && !in.PolicyApprovalGranted:
		call.set(toolOutcomeHeld)
		return s.auditedDenial(ctx, p, in, reason+"; approval must be resolved before activity execution")
	}
	conn, refusal, err := s.callConnection(ctx, ws, in)
	if err != nil {
		return ToolResult{}, err
	}
	if refusal != "" {
		call.set(toolOutcomeDenied)
		return s.auditedDenial(ctx, p, in, refusal)
	}
	b, refusal := s.beforeCall(ctx, p, in, conn)
	if refusal == "" {
		var pending *pendingCost
		if b.converted {
			pending = &pendingCost{amount: b.amount, currency: b.currency}
		}
		refusal, err = s.toolSpendRefusal(ctx, ws, p, in, conn, pending)
		if err != nil {
			s.voidHold(ctx, b.holdID, "the spend gate failed")
			return ToolResult{}, err
		}
		if refusal != "" {
			s.voidHold(ctx, b.holdID, "refused by a spend cap")
		}
	}
	if refusal != "" {
		call.set(toolOutcomeDenied)
		return s.auditedDenial(ctx, p, in, refusal)
	}
	out, err := s.dispatch(ctx, p, in, call)
	if err != nil {
		s.voidHold(ctx, b.holdID, "the call raised")
		return ToolResult{}, err
	}
	call.answered(out.Success)
	if !out.Success {
		s.voidHold(ctx, b.holdID, "the call failed")
	}
	res := ToolResult{Out: out, CostMetered: true, Replayed: out.Replayed}
	if conn != nil {
		res.Payer = conn.payer
	}
	for _, pay := range out.Payments {
		if pay.AlreadySettled {
			res.Replayed = true
		}
	}
	if res.Images, res.Out.Result, err = s.keepOutput(ctx, p, in, out); err != nil {
		return ToolResult{}, err
	}
	usages := s.meter(ctx, in, conn, out, b)
	if len(usages) > 0 {
		inserted, err := s.ledger(ctx, ws, p, in, conn, usages)
		if err != nil {
			res.CostMetered = false
			s.d.Log.ErrorContext(ctx, "tool call ran but its cost lines were not recorded", "call", callRef(in), "error", err)
		} else if inserted < len(usages) {
			res.Replayed = true
		}
		if res.Replayed && out.Success {
			s.voidHold(ctx, b.holdID, "the call's line was already recorded")
		}
	}
	deployment := string(s.d.Pricing.Currency())
	for _, u := range usages {
		if u.payer != payerPerCall && u.currency == deployment {
			res.Cost = res.Cost.Add(u.amount)
		}
	}
	if in.Attempt > 1 {
		attempt := in.Attempt
		res.Attempt = &attempt
	}
	return res, nil
}

type pendingCost struct {
	amount   money.Decimal
	currency string
}

// beforeCall is _before: the call's cost before it runs and, on the
// platform's key, its hold, or why the call is refused.
func (s *Service) beforeCall(ctx context.Context, p Principal, in ToolCall, conn *connection) (before, string) {
	if conn == nil || conn.cost == nil {
		return before{}, ""
	}
	model, err := costModelOf(conn.cost)
	if err != nil {
		return before{}, "the cost of this call cannot be known: " + costReason(err)
	}
	cost, err := preCallCost(model, in.Args)
	if err != nil {
		return before{}, "the cost of this call cannot be known: " + costReason(err)
	}
	b := before{model: &model, cost: cost}
	ref := conn.connector + "#" + conn.tool
	convert := func() (before, string) {
		if cost != nil {
			b.amount, b.currency, b.pending = s.convertCost(ctx, conn.payer, conn.connector, conn.tool, cost.vendorCost, cost.currency, money.KindTool)
			b.converted = true
		}
		return b, ""
	}
	if conn.payer != payerPlatform || model.source == sourceFree {
		return convert()
	}
	if model.source == sourceUnknown {
		return before{}, ref + " runs on the platform's key but its connector declares no cost"
	}
	if s.d.Billing == nil {
		return convert()
	}
	if cost == nil {
		return before{}, ref + " runs on the platform's key but declares neither a rate nor an estimate to hold"
	}
	bctx, cancel := s.billingCtx(ctx)
	defer cancel()
	hold, err := s.d.Billing.Authorize(bctx, money.AuthorizeRequest{
		WorkspaceID: p.WorkspaceID, Connector: conn.connector, Tool: conn.tool, VendorCost: cost.vendorCost,
		VendorCurrency: money.Currency(cost.currency), Quantity: cost.quantity, Unit: cost.unit,
		IdempotencyKey: "hold:" + callRef(in), Kind: money.KindTool,
	})
	if err != nil {
		s.d.Log.ErrorContext(ctx, "billing could not authorize the tool call", "connection", ref, "call", callRef(in), "error", err)
		return before{}, "billing_unavailable: billing is temporarily unavailable"
	}
	if !hold.Allowed {
		return before{}, hold.Code + ": " + hold.Reason
	}
	b.holdID, b.heldCurrent, b.converted, b.currency = hold.HoldID, string(hold.Currency), true, string(hold.Currency)
	if hold.Amount != nil {
		b.heldAmount, b.amount = *hold.Amount, *hold.Amount
	}
	return b, ""
}

func unitOf(c *api.ToolCost) string {
	if c.Unit == "" {
		return "call"
	}
	return c.Unit
}

func (s *Service) voidHold(ctx context.Context, holdID, why string) {
	s.releaseHold(ctx, funding{holdID: holdID}, why)
}

// auditedDenial refuses the call and records the refusal once per activity.
func (s *Service) auditedDenial(ctx context.Context, p Principal, in ToolCall, reason string) (ToolResult, error) {
	if s.d.Audit != nil {
		ws, err := workspace(p)
		if err != nil {
			return ToolResult{}, err
		}
		line := domain.AuditLine{
			EventID: uuid.NewSHA1(uuid.NameSpaceURL, []byte("tool-denied:"+in.RunID+":"+in.ActivityID)).String(),
			Action:  domain.AuditToolCallDenied, TaskID: in.TaskID, ActorType: "agent", ActorID: p.AgentID,
			Metadata: map[string]any{
				"tool": in.ToolName, "task_id": in.TaskID, "agent_id": p.AgentID, "tool_call_id": in.ToolCallID,
				"decision": "denied", "reason": reason, "argument_keys": domain.ArgumentKeys(in.Args), "requested_by": p.UserID,
			},
		}
		if err := s.d.DB.Write(ctx, ws, func(ctx context.Context, tx db.Session) error {
			return s.d.Audit.RecordOnce(ctx, tx, auditRecord(line))
		}); err != nil {
			return ToolResult{}, err
		}
	}
	return deniedResult(reason), nil
}

// toolSpendRefusal is spend_cap_refusal: every cap the call falls under,
// summed over its current lines, with the call's known cost counted.
func (s *Service) toolSpendRefusal(ctx context.Context, ws scope.Workspace, p Principal, in ToolCall, conn *connection, pending *pendingCost) (string, error) {
	budget := in.Policy.Budget
	if s.d.Caps != nil {
		live, err := s.budget(ctx, p)
		if err != nil {
			return "", err
		}
		budget = mergeBudget(live, in.Policy.Budget)
	}
	caps := toolSpendCaps(budget, toolCallScope{
		TaskID: in.TaskID, AgentID: p.AgentID, ClientID: in.ClientID, HasConnection: conn != nil, ConnectionID: connID(conn), Tool: connTool(conn),
	}, string(s.d.Pricing.Currency()))
	if len(caps) == 0 {
		return "", nil
	}
	now := s.now()
	var refusal string
	err := s.readSession(ctx, ws, func(tx db.Session) error {
		for _, c := range caps {
			since := monthStart(now)
			if c.PerRun {
				since = time.Unix(0, 0)
			}
			spent, err := s.sum(ctx, tx, since, c.Currency, c.Scope)
			if err != nil {
				return err
			}
			var pendingAmount *money.Decimal
			if pending != nil && pending.currency == c.Currency {
				pendingAmount = &pending.amount
			}
			if refusal = c.refusal(spent, pendingAmount); refusal != "" {
				return nil
			}
		}
		return nil
	})
	return refusal, err
}

func connID(c *connection) string {
	if c == nil {
		return ""
	}
	return c.id
}

func connTool(c *connection) string {
	if c == nil {
		return ""
	}
	return c.tool
}

// dispatch runs the call on its binding source's caller; a failure is the tool's answer.
func (s *Service) dispatch(ctx context.Context, p Principal, in ToolCall, call *toolCall) (ToolOutput, error) {
	caller, ok := s.d.Tools[in.Binding.Source]
	if sb := s.sandboxCaller(in); sb != nil {
		caller, ok = sb, true
	}
	if w := s.webCaller(in); w != nil {
		caller, ok = w, true
	}
	if c := s.contextCaller(in); c != nil {
		caller, ok = c, true
	}
	if m := s.mediaCaller(in); m != nil {
		caller, ok = m, true
	}
	if l := s.llmCaller(in); l != nil {
		caller, ok = l, true
	}
	if !ok {
		return ToolOutput{Result: fmt.Sprintf("MCP tool error: Unknown tool: %s", in.ToolName), Error: "Unknown tool: " + in.ToolName, Source: "builtin"}, nil
	}
	out, err := caller.Call(ctx, ToolInvocation{
		Principal: p, TaskID: in.TaskID, ExecutionID: in.ExecutionID, WorkflowID: in.WorkflowID, ToolCallID: in.ToolCallID,
		ToolName: in.ToolName, Args: in.Args, Binding: in.Binding, RunMetadata: in.RunMetadata, CallRef: callRef(in),
		Progress: s.progressRelay(ctx, p, in),
	})
	if err == nil {
		return out, nil
	}
	if ctx.Err() != nil {
		return ToolOutput{}, err
	}
	var unreachable *UnreachableError
	if errors.As(err, &unreachable) {
		return ToolOutput{}, err
	}
	s.d.Log.ErrorContext(ctx, "tool execution failed", "tool", in.ToolName, "error", err)
	call.failed(err)
	source := in.Binding.Source
	if source == "code" || source == "" {
		source = "builtin"
	}
	return ToolOutput{Result: fmt.Sprintf("MCP tool error: %T: %v", err, err), Error: err.Error(), Source: source}, nil
}

// progressRelay heartbeats on every notice and broadcasts at most one tool.progress per interval.
func (s *Service) progressRelay(ctx context.Context, p Principal, in ToolCall) func(ToolProgress) {
	var mu sync.Mutex
	var recorded time.Time
	return func(pr ToolProgress) {
		if in.Heartbeat != nil {
			in.Heartbeat()
		}
		mu.Lock()
		now := time.Now()
		finished := pr.Total != nil && pr.Progress >= *pr.Total
		if !recorded.IsZero() && now.Sub(recorded) < toolProgressInterval && !finished {
			mu.Unlock()
			return
		}
		recorded = now
		mu.Unlock()
		if s.d.Events == nil {
			return
		}
		var total, message any
		if pr.Total != nil {
			total = *pr.Total
		}
		if pr.Message != "" {
			message = pr.Message
		}
		e := taskEvent(in.TaskID, p.WorkspaceID, domain.EventToolProgress, newID(), s.now(), map[string]any{
			"task_id": in.TaskID, "tool_name": in.ToolName, "tool_call_id": in.ToolCallID,
			"progress": pr.Progress, "total": total, "message": message,
		}, nil)
		if err := s.d.Events.Broadcast(ctx, e); err != nil {
			s.d.Log.WarnContext(ctx, "failed to record tool progress", "tool_call_id", in.ToolCallID, "task_id", in.TaskID, "error", err)
		}
	}
}

func outputID(prefix, activityID string) string {
	var b strings.Builder
	for _, r := range activityID {
		if r == '-' || r == '_' || ('0' <= r && r <= '9') || ('a' <= r && r <= 'z') || ('A' <= r && r <= 'Z') {
			b.WriteRune(r)
		} else {
			b.WriteByte('_')
		}
	}
	if activityID == "" {
		b.WriteString(prefix)
	}
	return prefix + "_" + b.String()
}

// keepOutput stores the tool's images and offloads a result over the offload
// size to a task file; read_file's own result is never offloaded.
func (s *Service) keepOutput(ctx context.Context, p Principal, in ToolCall, out ToolOutput) ([]domain.ImageRef, string, error) {
	prefix := "tool"
	if in.Binding.Source == "mcp" {
		prefix = "mcp_tool"
	}
	id := outputID(prefix, in.ActivityID)
	var refs []domain.ImageRef
	var notes []string
	if len(out.Images) > 0 && in.TaskID == "" {
		notes = append(notes, fmt.Sprintf("[%d image(s) not kept: the call belongs to no task]", len(out.Images)))
	} else {
		for i, img := range out.Images {
			info, isImage, err := inspectImage(img.Data)
			if img.MimeType == pdfMimeType {
				info, isImage, err = imageInfo{MimeType: pdfMimeType}, true, nil
			}
			if !isImage || err != nil {
				reason := fmt.Sprintf("%s is not PNG, JPEG, GIF or WebP", img.MimeType)
				if err != nil {
					reason = err.Error()
				}
				notes = append(notes, fmt.Sprintf("[image %d not kept: %s]", i+1, reason))
				continue
			}
			imageID := domain.StoredImageID(id, i+1)
			if err := s.putText(ctx, domain.ImageKey(p.WorkspaceID, in.TaskID, imageID), string(img.Data), info.MimeType); err != nil {
				s.d.Log.WarnContext(ctx, "tool image could not be stored", "image_id", imageID, "error", err)
				notes = append(notes, fmt.Sprintf("[image %d could not be stored]", i+1))
				continue
			}
			refs = append(refs, domain.ImageRef{ID: imageID, MimeType: info.MimeType, Size: int64(len(img.Data)),
				Width: info.Width, Height: info.Height, Pages: img.Pages})
		}
	}
	content := strings.Join(append([]string{out.Result}, notes...), "\n")
	if len(notes) == 0 {
		content = out.Result
	}
	if content == "" || len([]rune(content)) <= domain.OutputOffloadChars || in.TaskID == "" || domain.IsReadFile(in.ToolName, in.Binding) {
		return refs, content, nil
	}
	files := filesTask(ToolInvocation{TaskID: in.TaskID, RunMetadata: in.RunMetadata})
	path, err := s.keepToolOutput(ctx, p, in.TaskID, files, in.WorkflowID, id, content)
	if err != nil {
		s.d.Log.WarnContext(ctx, "activity output offload failed", "output_id", id, "error", err)
		head := string([]rune(content)[:domain.OutputOffloadChars])
		return refs, fmt.Sprintf("%s\n... [activity output truncated at %d chars; offload failed: %v]", head, domain.OutputOffloadChars, err), nil
	}
	return refs, domain.OutputSummary(content, path), nil
}

// meter is the call's lines: its connection's cost when it answered, and each settled wallet payment.
func (s *Service) meter(ctx context.Context, in ToolCall, conn *connection, out ToolOutput, b before) []usage {
	var lines []usage
	if conn != nil && out.Success {
		if u, ok := s.connectionLine(ctx, in, conn, out, b); ok {
			lines = append(lines, u)
		}
	}
	for _, pay := range out.Payments {
		if !pay.Settled {
			continue
		}
		connector, tool := "", in.ToolName
		if conn != nil {
			connector, tool = conn.connector, conn.tool
		}
		amount, currency, pending := s.convertCost(ctx, payerPerCall, connector, tool, pay.Amount, walletCurr, money.KindTool)
		evidence := map[string]any{}
		for k, v := range map[string]string{"protocol": pay.Protocol, "recipient": pay.Recipient, "tx_hash": pay.TxHash} {
			if v != "" {
				evidence[k] = v
			}
		}
		if pending {
			evidence["settle"], evidence["vendor_exact"] = settleConvert, true
		}
		lines = append(lines, usage{
			lineKey: callRef(in) + ":payment:" + pay.IdempotencyKey, payer: payerPerCall, source: sourceReport, unit: "payment",
			quantity: money.FromInt(1), vendorCost: pay.Amount, vendorCurrency: walletCurr, amount: amount, currency: currency,
			estimate: pending, evidence: evidence,
		})
	}
	return lines
}

// connectionLine is _connection_line: what the call cost by its connector's declaration.
func (s *Service) connectionLine(ctx context.Context, in ToolCall, conn *connection, out ToolOutput, b before) (usage, bool) {
	cost, err := s.meteredCall(conn, in, out, b)
	if err != nil {
		if b.holdID == "" {
			s.d.Log.ErrorContext(ctx, "tool call could not be metered; no line recorded", "call", callRef(in), "connection", conn.connector+"#"+conn.tool, "error", err)
			return usage{}, false
		}
		s.d.Log.ErrorContext(ctx, "tool call could not be metered; its hold is captured at the estimate", "call", callRef(in), "connection", conn.connector+"#"+conn.tool, "error", err)
		cost = b.cost
	}
	if cost == nil {
		return usage{}, false
	}
	u := usage{
		lineKey: callRef(in), payer: conn.payer, source: cost.source, unit: cost.unit, quantity: cost.quantity,
		vendorCost: cost.vendorCost, vendorCurrency: cost.currency, evidence: map[string]any{},
	}
	settles := cost.source == sourceSettled
	if b.holdID != "" {
		u.amount, u.currency, u.estimate = b.heldAmount, b.heldCurrent, true
		u.evidence["hold_id"], u.evidence["settle"] = b.holdID, settleCapture
		if settles {
			u.evidence["settle"] = settleVendor
		}
		withSettleParams(u.evidence, cost)
		return u, true
	}
	pending := false
	if b.converted && b.cost != nil && b.cost.vendorCost.Equal(cost.vendorCost) && b.cost.currency == cost.currency {
		u.amount, u.currency, pending = b.amount, b.currency, b.pending
	} else {
		u.amount, u.currency, pending = s.convertCost(ctx, conn.payer, conn.connector, conn.tool, cost.vendorCost, cost.currency, money.KindTool)
	}
	settle := ""
	switch {
	case settles:
		settle = settleVendor
	case pending:
		settle = settleConvert
	}
	if settle != "" {
		u.evidence["settle"] = settle
		withSettleParams(u.evidence, cost)
	}
	if settle == settleConvert {
		u.evidence["vendor_exact"] = cost.exact
	}
	u.estimate = !cost.exact || settle != ""
	return u, true
}

func withSettleParams(evidence map[string]any, cost *meteredCost) {
	if len(cost.settleParams) == 0 {
		return
	}
	params := make(map[string]any, len(cost.settleParams))
	for k, v := range cost.settleParams {
		params[k] = v
	}
	evidence["settle_params"] = params
}

// meteredCall: a declared cost is metered from the call's arguments and
// result; a flat one is its price per call, or the cost the connector reported.
func (s *Service) meteredCall(conn *connection, in ToolCall, out ToolOutput, b before) (*meteredCost, error) {
	if conn.cost != nil && conn.cost.Declaration != nil {
		if b.model == nil {
			return nil, nil
		}
		return meterCost(*b.model, in.Args, out.MeteredBody, out.MeteredMeta)
	}
	one := money.FromInt(1)
	switch {
	case out.VendorCost != nil:
		currency := walletCurr
		if conn.cost != nil {
			currency = conn.cost.VendorCurrency
		}
		unit := "call"
		if conn.cost != nil {
			unit = unitOf(conn.cost)
		}
		return &meteredCost{quantity: one, unit: unit, vendorCost: *out.VendorCost, currency: currency, source: sourceReport, exact: true}, nil
	case conn.cost != nil:
		return &meteredCost{quantity: one, unit: unitOf(conn.cost), vendorCost: conn.cost.VendorCost, currency: conn.cost.VendorCurrency, source: sourceRate, exact: true}, nil
	}
	return nil, nil
}

// ledger writes the call's lines once per line key; how many were new.
func (s *Service) ledger(ctx context.Context, ws scope.Workspace, p Principal, in ToolCall, conn *connection, usages []usage) (int, error) {
	inserted := 0
	err := s.d.DB.Write(ctx, ws, func(ctx context.Context, tx db.Session) error {
		var chain struct{ CorrelationID, CausationID string }
		if in.TaskID != "" {
			task, err := s.store.Task(ctx, tx, in.TaskID)
			if err != nil {
				return err
			}
			chain.CorrelationID, chain.CausationID = task.CorrelationID, task.CausationID
		}
		for _, u := range usages {
			line := toolCostLine(in, p, conn, u, s.now())
			ok, err := s.store.InsertCostLine(ctx, tx, line, p.UserID, store.TaskRef{ID: in.TaskID, CorrelationID: chain.CorrelationID, CausationID: chain.CausationID})
			if err != nil {
				return err
			}
			if ok {
				inserted++
			}
		}
		return nil
	})
	return inserted, err
}

func toolCostLine(in ToolCall, p Principal, conn *connection, u usage, now time.Time) domain.CostLine {
	subjectName := in.ToolName
	var subjectID *string
	evidence := map[string]any{"tool_name": in.ToolName}
	if conn != nil {
		if conn.tool != "" {
			subjectName = conn.tool
		}
		id := conn.id
		subjectID = &id
		if conn.connector != "" {
			evidence["connector"] = conn.connector
		}
	}
	for k, v := range u.evidence {
		evidence[k] = v
	}
	ref := callRef(in)
	vendor, quantity, unit := u.vendorCost.String(), u.quantity.String(), u.unit
	vendorCurrency := u.vendorCurrency
	return domain.CostLine{
		EventID: uuid.NewSHA1(uuid.MustParse(toolCallEvents), []byte(u.lineKey)).String(), Category: domain.CostService,
		TaskID: in.TaskID, AgentID: p.AgentID, SubjectType: domain.SubjectTool, SubjectID: subjectID,
		SubjectName: capped(subjectName), CallRef: capped(ref), Amount: u.amount.String(), Currency: u.currency,
		Source: u.source, Payer: u.payer, Evidence: evidence, VendorCost: &vendor, VendorCurrency: &vendorCurrency,
		Estimate: u.estimate, OccurredAt: now, Quantity: &quantity, Unit: &unit, ClientID: in.ClientID,
	}
}

func capped(s string) *string {
	r := []rune(s)
	if len(r) > 255 {
		s = string(r[:255])
	}
	return &s
}
