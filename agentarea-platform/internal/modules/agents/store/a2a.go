package store

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
)

// A2AAgent is get_public_agent: the agent by id in whichever workspace holds
// it, archived included. A discovery URL names an agent, not a workspace.
func A2AAgent(ctx context.Context, q db.Querier, id uuid.UUID) (domain.Agent, bool, error) {
	r, err := New(q).A2AAgent(ctx, id)
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Agent{}, false, nil
	}
	if err != nil {
		return domain.Agent{}, false, err
	}
	return agent(GetAgentRow(r)), true, nil
}
