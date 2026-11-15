// Package service of insights: use cases; one file per Python service file. deps.go declares what it needs from other modules (rule 2).
package service

import (
	"context"
	"log/slog"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	connectionsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	identityapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/api"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	streamsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/api"
	walletapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/api"
)

// Installations is the installation store (store.Installation).
type Installations interface {
	GetOrCreate(ctx context.Context, g db.Global, now time.Time) (string, error)
}

// Balance answers the paying account's balance (the account_balance extension).
// Nil in a self-hosted install, which sells none.
type Balance = money.BalanceSource

// Reads are the other modules' reads the dashboard, the agent overview, the
// settings and the network graph are built from. Pricing nil is USD at
// provider cost; Usage nil meters no runtime.
type Reads struct {
	Ledger      runsapi.SpendLedger
	Tasks       runsapi.TaskBoard
	Triggers    streamsapi.TriggerBoard
	AllTriggers streamsapi.Triggers
	Wallets     walletapi.Wallets
	Connections connectionsapi.ConnectionBoard
	Specs       catalogapi.MCPSpecs
	Agents      agentsapi.Network
	Lookup      agentsapi.Lookup
	Caps        governanceapi.SpendCaps
	Owners      identityapi.WorkspaceOwners
	Members     authz.Reader
	Pricing     money.CustomerPricing
	Usage       money.UsageSource
}

// Deps are the service's ports.
type Deps struct {
	DB            db.Database
	Installations Installations
	// Balance is nil when the deployment sells no balance.
	Balance Balance
	Reads   Reads
	// Admin is nil for a workspace admin of the caller's workspace and
	// authz.ErrNotWorkspaceAdmin otherwise.
	Admin func(ctx context.Context) error
	// AnalyticsEnabled and Edition come from insights.Config.
	AnalyticsEnabled bool
	Edition          string
	// Now is the clock installation timestamps are written in; nil is time.Now.
	Now func() time.Time
	Log *slog.Logger
}
