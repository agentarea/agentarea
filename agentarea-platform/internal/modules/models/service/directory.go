package service

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/store"
)

var _ api.Directory = (*Service)(nil)

// InstancesOfKind are the active instances of kind the workspace sees (the newest 100, as list_model_instances).
func (s *Service) InstancesOfKind(ctx context.Context, ws scope.Workspace, kind string) ([]api.InstanceName, error) {
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return nil, err
	}
	defer release()
	active := true
	ins, err := s.st.Instances(ctx, sess, store.InstanceFilter{IsActive: &active})
	if err != nil {
		return nil, err
	}
	views, err := s.instanceViews(ctx, sess, ws, ins)
	if err != nil {
		return nil, err
	}
	out := []api.InstanceName{}
	for _, v := range views {
		if v.Model == nil || v.Model.Kind != kind {
			continue
		}
		out = append(out, api.InstanceName{ID: v.ID, Name: v.Name, ModelName: v.Model.ModelName, Kind: kind})
	}
	return out, nil
}

// BillingCurrency is the currency the deployment's customer pricing bills in.
func (s *Service) BillingCurrency() string { return string(s.Currency()) }
