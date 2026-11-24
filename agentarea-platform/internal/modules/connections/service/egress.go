package service

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/store"
)

// BoundToEgressExit is the workspace's instances whose json_spec binds the exit.
func (s *Service) BoundToEgressExit(ctx context.Context, ws scope.Workspace, exitID string) ([]api.EgressBoundInstance, error) {
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return nil, err
	}
	defer release()
	return store.EgressBound(ctx, sess, exitID)
}

// RetireBeforeMutation is retire_runtime_before_mutation.
func (s *Service) RetireBeforeMutation(ctx context.Context, instanceID string) error {
	return s.retire(ctx, instanceID)
}
