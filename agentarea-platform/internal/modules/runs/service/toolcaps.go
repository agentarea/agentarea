package service

import (
	"fmt"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
)

// toolCallScope is what of a call the caps narrow by.
type toolCallScope struct {
	TaskID, AgentID    string
	ClientID           string
	HasConnection      bool
	ConnectionID, Tool string
}

// spendCap is one cap a tool call falls under (spend_gate.py _Cap).
type spendCap struct {
	Label    string
	Amount   money.Decimal
	Currency string
	Scope    store.SpendScope
	PerRun   bool
}

func monthlyLabel(narrowed string) string {
	switch narrowed {
	case "":
		return "workspace monthly"
	case "agent":
		return "agent monthly"
	case "tools":
		return "monthly tools"
	}
	return narrowed
}

// toolSpendCaps are the caps a tool call falls under; a cap on LLM spend never refuses one.
func toolSpendCaps(budget *api.BudgetPolicy, call toolCallScope, billing string) []spendCap {
	if budget == nil {
		return nil
	}
	var caps []spendCap
	if budget.MonthlySpendCap != nil {
		caps = append(caps, spendCap{Label: "workspace monthly", Amount: *budget.MonthlySpendCap, Currency: billing})
	}
	if budget.RunBudget != nil && call.TaskID != "" {
		caps = append(caps, spendCap{Label: "run", Amount: *budget.RunBudget, Currency: billing, Scope: store.SpendScope{TaskID: call.TaskID}, PerRun: true})
	}
	if budget.AgentMonthlySpendCap != nil && call.AgentID != "" {
		caps = append(caps, spendCap{Label: "agent monthly", Amount: *budget.AgentMonthlySpendCap, Currency: billing, Scope: store.SpendScope{AgentID: call.AgentID}})
	}
	for _, c := range budget.SpendCaps {
		perRun := c.Period == "run"
		switch {
		case c.Category == "llm",
			c.Category == "tools" && !call.HasConnection && c.Tool == "",
			perRun && call.TaskID == "",
			c.ClientID != "" && c.ClientID != call.ClientID,
			c.ConnectionID != "" && (!call.HasConnection || c.ConnectionID != call.ConnectionID),
			c.Tool != "" && (!call.HasConnection || c.Tool != call.Tool),
			c.OwnAgent && call.AgentID == "":
			continue
		}
		narrowed := ""
		switch {
		case c.Tool != "":
			narrowed = "tool"
		case c.ConnectionID != "":
			narrowed = "connection"
		case c.ClientID != "":
			narrowed = "client"
		case c.Category == "tools":
			narrowed = "tools"
		case c.OwnAgent:
			narrowed = "agent"
		}
		label := monthlyLabel(narrowed)
		if perRun {
			label = strings.TrimSpace("run " + narrowed)
		}
		scope := store.SpendScope{ConnectionID: c.ConnectionID, Tool: c.Tool, ClientID: c.ClientID}
		if c.OwnAgent {
			scope.AgentID = call.AgentID
		}
		if perRun {
			scope.TaskID = call.TaskID
		}
		if c.Category == "tools" {
			scope.Category = domain.CostService
		}
		currency := c.Currency
		if currency == "" {
			currency = billing
		}
		caps = append(caps, spendCap{Label: label, Amount: c.Amount, Currency: currency, Scope: scope, PerRun: perRun})
	}
	return caps
}

// normalized is format(d.normalize(), "f"): no trailing zeros, no exponent.
func normalized(d money.Decimal) string {
	s := d.Plain()
	if strings.Contains(s, ".") {
		s = strings.TrimRight(strings.TrimRight(s, "0"), ".")
	}
	if s == "-0" {
		s = "0"
	}
	return s
}

// refusal says why the cap refuses the call, or "" when it allows it.
func (c spendCap) refusal(spent money.Decimal, pending *money.Decimal) string {
	period := "this month"
	if c.PerRun {
		period = "in this run"
	}
	if spent.Cmp(c.Amount) >= 0 {
		return fmt.Sprintf("%s spend cap of %s %s reached: %s %s spent %s", c.Label, normalized(c.Amount), c.Currency, normalized(spent), c.Currency, period)
	}
	if pending != nil && spent.Add(*pending).Cmp(c.Amount) > 0 {
		return fmt.Sprintf("%s spend cap of %s %s would be exceeded: %s %s spent %s, this call costs %s %s",
			c.Label, normalized(c.Amount), c.Currency, normalized(spent), c.Currency, period, normalized(*pending), c.Currency)
	}
	return ""
}
