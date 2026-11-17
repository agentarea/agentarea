package service

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
)

var _ api.MCPToolCatalogue = (*Service)(nil)

// ToolInstances is the instances GET /agents/tools lists MCP tools from.
func (s *Service) ToolInstances(ctx context.Context, c authn.Caller, instanceID string) ([]api.ToolInstance, error) {
	var rows []domain.Instance
	if instanceID == "" {
		all, _, err := s.listInstances(ctx, c)
		if err != nil {
			return nil, err
		}
		rows = all
	} else {
		id, err := uuid.Parse(instanceID)
		if err != nil {
			return nil, err
		}
		if err := s.read(ctx, c, func(sess db.Session) error {
			i, ok, err := s.d.Instances.Get(ctx, sess, id)
			if ok {
				rows = []domain.Instance{i}
			}
			return err
		}); err != nil {
			return nil, err
		}
	}
	out := make([]api.ToolInstance, len(rows))
	for i, r := range rows {
		out[i] = api.ToolInstance{ID: r.ID, Name: r.Name, Tools: r.AvailableTools()}
	}
	return out, nil
}
