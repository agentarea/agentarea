package runs

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/service"
)

// SpendLedger is the cost ledger totals the dashboard and the agent overview show.
func (m *Surface) SpendLedger() api.SpendLedger { return service.InsightsReads{DB: m.d.Service.DB} }

// TaskBoard is the task lists and counts the dashboard and the agent overview show.
func (m *Surface) TaskBoard() api.TaskBoard { return service.InsightsReads{DB: m.d.Service.DB} }
