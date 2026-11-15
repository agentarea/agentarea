package app

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/insights"
)

// insightsPorts are the reads insights takes from modules built after it.
func insightsPorts(d coreDeps, m *moduleSet) insights.Later {
	var pricing money.CustomerPricing
	var usage money.UsageSource
	if d.Extensions != nil {
		pricing, usage = d.Extensions.CustomerPricing, d.Extensions.WorkspaceUsage
	}
	return insights.Later{
		Ledger: m.runsSurface.SpendLedger(), Tasks: m.runsSurface.TaskBoard(),
		Triggers: m.streams.TriggerBoard(), AllTriggers: m.streams.Triggers(),
		Wallets: m.wallet.Wallets(), Connections: m.connections.ConnectionBoard(), Specs: m.catalog.MCPSpecs(),
		Agents: m.agents.Network(), Lookup: m.agents.Lookup(), Caps: m.governance.SpendCaps(),
		Owners: m.identity.WorkspaceOwners(), Members: d.Graph, Pricing: pricing, Usage: usage,
	}
}
