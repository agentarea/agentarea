package service

import (
	"context"
	"errors"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/mcpserver"
)

// ClientCaller is p acting in the workspace of the client clientID names, for MCP Events on
// /mcp/clients/{id} (client_events_context); false when p reaches no such client or may not use it.
func (s *Service) ClientCaller(ctx context.Context, p authn.Principal, clientID string, enter EnterWorkspace) (authn.Caller, bool, error) {
	id, err := uuid.Parse(clientID)
	if err != nil {
		return authn.Caller{}, false, nil
	}
	clientID = id.String()
	wsID, ok, err := s.d.ClientBundles.Locate(ctx, clientID, p.AccessibleWorkspaces)
	if err != nil || !ok {
		return authn.Caller{}, false, err
	}
	if err := s.authorizeClient(ctx, p, clientID); err != nil {
		var refused *mcpserver.Refusal
		if errors.As(err, &refused) {
			return authn.Caller{}, false, nil
		}
		return authn.Caller{}, false, err
	}
	c, err := enter(ctx, p, wsID)
	return c, err == nil, err
}
