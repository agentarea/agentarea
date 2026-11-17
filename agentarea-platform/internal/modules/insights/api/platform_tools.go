package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
)

// PlatformNetwork is what the platform network toolset calls
// (tools/network_toolset.py); every member sees the workspace graph.
type PlatformNetwork interface {
	// Topology is GET /network/topology's NetworkTopologyResponse body.
	Topology(ctx context.Context, c authn.Caller) (any, error)
}
