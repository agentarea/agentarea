package mcpserver

import (
	"context"
	"encoding/json"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	insightsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/insights/api"
)

// networkTools is tools/network_toolset.py.
func networkTools(n insightsapi.PlatformNetwork) map[string]toolDef {
	return map[string]toolDef{
		"get_topology": {title: "Get network topology", effect: effectRead, call: func(ctx context.Context, c authn.Caller, _ json.RawMessage) (any, error) {
			return n.Topology(ctx, c)
		}},
	}
}
