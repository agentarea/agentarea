package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
)

// The settlement worker (cost_settlement.py): a ledger line marked
// evidence["settle"] that no line supersedes yet still waits on billing's
// capture of its hold, a vendor's settled figure, or a currency conversion.
// Each is finalised by an appended superseding line; the line is the work
// item, claimed across workspaces SKIP LOCKED, so any number of workers share
// the lines and a line settles once.

const (
	// settledLines is the namespace of a successor line's event id (_SETTLED_LINES).
	settledLines      = "2b9e4a6c-7d31-5f08-9c4e-1a5d8b3f6e27"
	sourceCostSettled = "settled"

	SettleTick        = 5 * time.Second
	settleBatch       = 20
	settleHorizon     = 7 * 24 * time.Hour
	settleMaxInterval = time.Hour
	// settleLease is how long a claim keeps a line from other workers; past
	// it the worker is taken for dead.
	settleLease = 10 * time.Minute
)

// errSettlement: a waiting line cannot be settled now; it is retried later.
var errSettlement = errors.New("settlement")

func settleErr(format string, a ...any) error {
	return fmt.Errorf("%w: %s", errSettlement, fmt.Sprintf(format, a...))
}

// RunSettlement settles waiting lines every tick until ctx ends (CostSettlement._run_loop).
func (s *Service) RunSettlement(ctx context.Context) error {
	t := time.NewTicker(SettleTick)
	defer t.Stop()
	for {
		if _, err := s.SettleBatch(ctx, s.now()); err != nil && ctx.Err() == nil {
			s.d.Log.ErrorContext(ctx, "cost settlement batch failed", "error", err)
		}
		select {
		case <-ctx.Done():
			return nil
		case <-t.C:
		}
	}
}

// SettleBatch settles the lines due at now; how many were finalised or
// advanced. The lines are claimed and committed first, so no transaction
// stays open while billing and vendors are asked; each outcome is then
// written in a short transaction of its own.
func (s *Service) SettleBatch(ctx context.Context, now time.Time) (int, error) {
	token := uuid.New()
	lines, err := s.claimSettlement(ctx, now, token)
	if err != nil {
		return 0, err
	}
	settled := 0
	var errs []error
	for _, line := range lines {
		inserted, err := s.settleLine(ctx, now, token, line)
		if err != nil {
			errs = append(errs, fmt.Errorf("line %s: %w", line.ID, err))
			continue
		}
		if inserted {
			settled++
		}
	}
	return settled, errors.Join(errs...)
}

// claimSettlement claims the lines due at now for token until settleLease
// ends, so a worker that dies leaves its lines to others after that. A line of
// an invalid workspace is dead.
func (s *Service) claimSettlement(ctx context.Context, now time.Time, token uuid.UUID) ([]store.UnsettledLine, error) {
	var out []store.UnsettledLine
	err := s.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		out = nil
		due, err := s.store.ClaimUnsettled(ctx, q, store.SettleClaim{
			Now: now, Since: now.Add(-settleHorizon), Tick: SettleTick, MaxInterval: settleMaxInterval, Limit: settleBatch,
		})
		if err != nil || len(due) == 0 {
			return err
		}
		claimed, err := s.store.ClaimLines(ctx, q, due, token, now, now.Add(settleLease))
		if err != nil {
			return err
		}
		var mine []store.UnsettledLine
		for _, l := range due {
			if claimed[l.ID] {
				mine = append(mine, l)
			}
		}
		live, err := s.store.DropSuperseded(ctx, q, append([]store.UnsettledLine(nil), mine...))
		if err != nil {
			return err
		}
		kept := map[string]bool{}
		for _, l := range live {
			kept[l.ID] = true
		}
		for _, l := range mine {
			if !kept[l.ID] {
				if err := s.store.ReleaseClaim(ctx, q, l.ID, token); err != nil {
					return err
				}
				continue
			}
			if _, err := scope.NewWorkspace(l.WorkspaceID, ""); err != nil {
				s.d.Log.ErrorContext(ctx, "line of an invalid workspace cannot be settled; it is dead", "line_id", l.ID, "workspace_id", l.WorkspaceID, "error", err)
				if err := s.store.KillClaim(ctx, q, l.ID, token, now, "invalid workspace: "+err.Error()); err != nil {
					return err
				}
				continue
			}
			out = append(out, l)
		}
		return nil
	})
	return out, err
}

// settleLine settles one claimed line with no transaction open, then records
// the outcome: the successor, a later retry, or a dead line billing rejected.
func (s *Service) settleLine(ctx context.Context, now time.Time, token uuid.UUID, line store.UnsettledLine) (bool, error) {
	ws, err := scope.NewWorkspace(line.WorkspaceID, "")
	if err != nil {
		return false, err
	}
	next, settleErr := s.settle(ctx, ws, line)
	switch {
	case errors.Is(settleErr, money.ErrBillingRejected):
		s.d.Log.ErrorContext(ctx, "billing rejected the line's settlement; it is dead", "line_id", line.ID,
			"event_id", line.Line.EventID, "settle", line.Line.Evidence["settle"], "error", settleErr)
	case settleErr != nil:
		s.d.Log.ErrorContext(ctx, "line could not be settled; retried later", "line_id", line.ID,
			"event_id", line.Line.EventID, "settle", line.Line.Evidence["settle"], "error", settleErr)
	}
	inserted := false
	err = s.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		inserted = false
		switch {
		case errors.Is(settleErr, money.ErrBillingRejected):
			return s.store.KillClaim(ctx, q, line.ID, token, now, settleErr.Error())
		case settleErr != nil:
			return s.store.DeferClaim(ctx, q, line.ID, token, now, SettleTick, settleMaxInterval)
		case next != nil:
			var err error
			if inserted, err = s.store.InsertSettledLine(ctx, q, ws, *next); err != nil {
				return err
			}
		}
		return s.store.ReleaseClaim(ctx, q, line.ID, token)
	})
	return inserted, err
}

// settle is the line that finalises line, or nil while what it waits on is not there yet.
func (s *Service) settle(ctx context.Context, ws scope.Workspace, line store.UnsettledLine) (*store.UnsettledLine, error) {
	kind, _ := line.Line.Evidence["settle"].(string)
	switch kind {
	case settleCapture:
		return s.settleCapture(ctx, line)
	case settleVendor:
		return s.settleVendor(ctx, ws, line)
	case settleConvert:
		return s.settleConvert(ctx, line)
	}
	return nil, settleErr("line %s waits on an unknown settlement %q", line.ID, line.Line.Evidence["settle"])
}

func evidenceString(e map[string]any, key string) string {
	switch v := e[key].(type) {
	case string:
		return v
	case nil:
		return ""
	default:
		return fmt.Sprint(v)
	}
}

func strOf(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

func decimalOr(p *string, fallback money.Decimal) (money.Decimal, error) {
	if p == nil || *p == "" {
		return fallback, nil
	}
	return money.Parse(*p)
}

// successor is _successor: the line that supersedes line, its settlement keys dropped.
func successor(line store.UnsettledLine, kind string, amount money.Decimal, currency string, estimate bool,
	vendorCost *money.Decimal, vendorCurrency *string, evidence map[string]any) *store.UnsettledLine {
	l := line.Line
	kept := map[string]any{}
	for k, v := range l.Evidence {
		if k != "settle" && k != "settle_params" && k != "vendor_exact" {
			kept[k] = v
		}
	}
	for k, v := range evidence {
		kept[k] = v
	}
	l.EventID = uuid.NewSHA1(uuid.MustParse(settledLines), []byte(l.EventID+":"+kind)).String()
	l.Amount, l.Currency, l.Estimate, l.Evidence = amount.String(), currency, estimate, kept
	if strings.HasPrefix(kind, settleVendor) {
		l.Source = sourceCostSettled
	}
	if vendorCost != nil {
		v := vendorCost.String()
		l.VendorCost = &v
	}
	if vendorCurrency != nil {
		l.VendorCurrency = vendorCurrency
	}
	return &store.UnsettledLine{WorkspaceID: line.WorkspaceID, CreatedBy: line.CreatedBy, ClientID: line.ClientID, SupersedesID: line.ID, Line: l}
}

func (s *Service) settleCapture(ctx context.Context, line store.UnsettledLine) (*store.UnsettledLine, error) {
	l := line.Line
	holdID := evidenceString(l.Evidence, "hold_id")
	if s.d.Billing == nil {
		return nil, settleErr("line %s holds %s but no billing is installed", line.ID, holdID)
	}
	if holdID == "" {
		return nil, settleErr("line %s waits on a capture but names no hold", line.ID)
	}
	vendorCost, err := decimalOr(l.VendorCost, money.Zero())
	if err != nil {
		return nil, err
	}
	quantity, err := decimalOr(l.Quantity, money.FromInt(1))
	if err != nil {
		return nil, err
	}
	unit := strOf(l.Unit)
	if unit == "" {
		unit = "call"
	}
	model := l.SubjectType == domain.SubjectModelInstance
	connector, tool, kind := evidenceString(l.Evidence, "connector"), strOf(l.SubjectName), money.KindTool
	if model {
		connector, tool, kind = modelConnector, strOf(l.SubjectID), money.KindModel
	}
	optional := func(s string) any {
		if s == "" {
			return nil
		}
		return s
	}
	bctx, cancel := s.billingCtx(ctx)
	defer cancel()
	charge, err := s.d.Billing.Capture(bctx, money.CaptureRequest{
		HoldID: holdID, WorkspaceID: line.WorkspaceID, Connector: connector, Tool: tool, VendorCost: vendorCost,
		VendorCurrency: money.Currency(strOf(l.VendorCurrency)), Quantity: quantity, Unit: unit,
		IdempotencyKey: "tool:" + l.EventID, Kind: kind,
		Metadata: map[string]any{
			"event_id": l.EventID, "call_ref": optional(strOf(l.CallRef)), "connection_id": optional(strOf(l.SubjectID)),
			"tool_name": l.Evidence["tool_name"], "task_id": optional(l.TaskID), "agent_id": optional(l.AgentID),
			"client_id": optional(line.ClientID), "occurred_at": pyISO(l.OccurredAt),
		},
	})
	if err != nil {
		return nil, fmt.Errorf("billing could not capture hold %s: %w", holdID, err)
	}
	return successor(line, settleCapture, charge.Amount, string(charge.Currency), false, nil, nil, nil), nil
}

func (s *Service) settleConvert(ctx context.Context, line store.UnsettledLine) (*store.UnsettledLine, error) {
	l := line.Line
	exact, _ := l.Evidence["vendor_exact"].(bool)
	vendorCost, err := decimalOr(l.VendorCost, money.Zero())
	if err != nil {
		return nil, err
	}
	amount, currency, pending := s.convertCost(ctx, l.Payer, evidenceString(l.Evidence, "connector"), strOf(l.SubjectName),
		vendorCost, strOf(l.VendorCurrency), lineKind(l))
	if pending {
		return nil, nil
	}
	return successor(line, settleConvert, amount, currency, !exact, nil, nil, nil), nil
}

// lineKind is what the line bought, for billing's quote. Python quoted every
// conversion as a tool's, a model line's included.
func lineKind(l domain.CostLine) money.BillingKind {
	if l.SubjectType == domain.SubjectModelInstance {
		return money.KindModel
	}
	return money.KindTool
}

// vendorCost is what the vendor says the line's call cost, nil while it is not done
// (vendor_settlement.make_vendor_settle).
func (s *Service) vendorCost(ctx context.Context, ws scope.Workspace, line store.UnsettledLine) (*meteredCost, error) {
	if s.d.Vendor == nil {
		return nil, settleErr("line %s waits on its vendor but no vendor settlement is wired", line.ID)
	}
	l := line.Line
	connectionID, tool := strOf(l.SubjectID), strOf(l.SubjectName)
	decl, err := s.d.Vendor.SettledDeclaration(ctx, ws, line.CreatedBy, connectionID, tool)
	if err != nil {
		return nil, fmt.Errorf("connection %s of line %s: %w", connectionID, line.ID, err)
	}
	model, err := parseCostModel(decl)
	if err != nil {
		return nil, err
	}
	if model.settle == nil {
		return nil, settleErr("connection %s declares no settled cost for %s", connectionID, tool)
	}
	params := map[string]string{}
	if raw, ok := l.Evidence["settle_params"].(map[string]any); ok {
		for k, v := range raw {
			params[k] = fmt.Sprint(v)
		}
	}
	url, err := settleURL(model.settle.url, params)
	if err != nil {
		return nil, err
	}
	status, body, err := s.d.Vendor.FetchSettlement(ctx, ws, line.CreatedBy, connectionID, url)
	if err != nil {
		return nil, err
	}
	if status == http.StatusNotFound {
		s.d.Log.WarnContext(ctx, "line settles at zero: the vendor has no record of it", "line_id", line.ID, "url", url)
		return &meteredCost{quantity: money.FromInt(1), unit: model.unit, vendorCost: money.Zero(), currency: model.currency, source: model.source, exact: true}, nil
	}
	if status < 200 || status >= 300 {
		return nil, settleErr("the vendor answered %d for %s", status, url)
	}
	var doc any
	dec := json.NewDecoder(strings.NewReader(string(body)))
	dec.UseNumber()
	if err := dec.Decode(&doc); err != nil {
		return nil, settleErr("the vendor's answer is not JSON: %v", err)
	}
	return settledCost(model, doc)
}

// settleURL is settle_url: the URL with the parameters the call returned, each fully escaped.
func settleURL(template string, params map[string]string) (string, error) {
	var missing error
	out := urlParamRe.ReplaceAllStringFunc(template, func(m string) string {
		name := m[1 : len(m)-1]
		v, ok := params[name]
		if !ok {
			missing = costErr("the line keeps no %s to settle with", name)
			return m
		}
		return quoteAll(v)
	})
	return out, missing
}

// quoteAll is urllib.parse.quote(s, safe=""): only unreserved bytes stay.
func quoteAll(s string) string {
	const hex = "0123456789ABCDEF"
	var b strings.Builder
	for i := 0; i < len(s); i++ {
		c := s[i]
		if ('A' <= c && c <= 'Z') || ('a' <= c && c <= 'z') || ('0' <= c && c <= '9') || c == '_' || c == '.' || c == '-' || c == '~' {
			b.WriteByte(c)
			continue
		}
		b.WriteByte('%')
		b.WriteByte(hex[c>>4])
		b.WriteByte(hex[c&15])
	}
	return b.String()
}

// settledCost is settled_cost: nil while the vendor's done field says it is not done.
func settledCost(m costModel, body any) (*meteredCost, error) {
	if m.settle.donePath != "" {
		v, err := readPath(body, m.settle.donePath)
		if err != nil {
			return nil, err
		}
		s, isStr := v.(string)
		done := false
		for _, want := range m.settle.doneIn {
			if isStr && s == want {
				done = true
			}
		}
		if !done {
			return nil, nil
		}
	}
	v, err := readPath(body, m.settle.costPath)
	if err != nil {
		return nil, err
	}
	cost, err := costDecimal(v, m.settle.costPath)
	if err != nil {
		return nil, err
	}
	return &meteredCost{quantity: money.FromInt(1), unit: m.unit, vendorCost: cost, currency: m.currency, source: m.source, exact: m.exact}, nil
}

func (s *Service) settleVendor(ctx context.Context, ws scope.Workspace, line store.UnsettledLine) (*store.UnsettledLine, error) {
	cost, err := s.vendorCost(ctx, ws, line)
	if err != nil || cost == nil {
		return nil, err
	}
	l := line.Line
	amount, err := money.Parse(l.Amount)
	if err != nil {
		return nil, err
	}
	lineVendor, err := decimalOr(l.VendorCost, money.Zero())
	if err != nil {
		return nil, err
	}
	currency := cost.currency
	confirmed := line.SupersedesID != "" && strOf(l.VendorCurrency) == cost.currency && lineVendor.Equal(cost.vendorCost)
	if !confirmed {
		kept := map[string]any{}
		for _, k := range []string{"settle", "settle_params"} {
			if v, ok := l.Evidence[k]; ok {
				kept[k] = v
			}
		}
		return successor(line, settleVendor+":"+cost.vendorCost.String(), amount, l.Currency, true, &cost.vendorCost, &currency, kept), nil
	}
	if l.Payer == payerPlatform && evidenceString(l.Evidence, "hold_id") != "" {
		return successor(line, settleVendor, amount, l.Currency, true, &cost.vendorCost, &currency, map[string]any{"settle": settleCapture}), nil
	}
	converted, convertedCurrency, pending := s.convertCost(ctx, l.Payer, evidenceString(l.Evidence, "connector"), strOf(l.SubjectName),
		cost.vendorCost, cost.currency, lineKind(l))
	var evidence map[string]any
	if pending {
		evidence = map[string]any{"settle": settleConvert, "vendor_exact": cost.exact}
	}
	return successor(line, settleVendor, converted, convertedCurrency, !cost.exact || pending, &cost.vendorCost, &currency, evidence), nil
}

// pyISO is datetime.isoformat() of an aware UTC instant.
func pyISO(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/1000 == 0 {
		return t.Format("2006-01-02T15:04:05") + "+00:00"
	}
	return t.Format("2006-01-02T15:04:05.000000") + "+00:00"
}
