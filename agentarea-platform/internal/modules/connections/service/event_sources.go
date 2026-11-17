package service

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
)

var _ api.MCPEventSources = (*Service)(nil)

// MCPEventSource is MCPServerInstanceRepository.get for an MCP Events source.
func (s *Service) MCPEventSource(ctx context.Context, ws scope.Workspace, id string) (api.MCPEventSource, bool, error) {
	parsed, err := uuid.Parse(id)
	if err != nil {
		return api.MCPEventSource{}, false, nil
	}
	var inst domain.Instance
	var ok bool
	err = s.readWS(ctx, ws, func(sess db.Session) error {
		inst, ok, err = s.d.Instances.Get(ctx, sess, parsed)
		return err
	})
	if err != nil || !ok {
		return api.MCPEventSource{}, false, err
	}
	return api.MCPEventSource{AuthConfigID: inst.AuthConfigID, ManagedBy: inst.ManagedBy, Events: inst.Events}, true, nil
}
