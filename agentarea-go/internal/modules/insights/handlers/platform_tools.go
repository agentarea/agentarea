package handlers

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/insights/service"
)

// PlatformTopology is network_get_topology: GET /network/topology's body.
func PlatformTopology(ctx context.Context, svc *service.Service, c authn.Caller) (any, error) {
	t, err := svc.Topology(ctx, c)
	if err != nil {
		return nil, err
	}
	return topologyJSON(t), nil
}
