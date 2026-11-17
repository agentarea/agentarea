package service

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
)

// ErrNotConnectionOwner is set_sharing's refusal (403).
var ErrNotConnectionOwner = &domain.Forbidden{Msg: "Only whoever added this connection can change who may use it."}

// SharingOf is sharing_of: personal from the graph, owned when the caller added it.
func (s *Service) SharingOf(ctx context.Context, c authn.Caller, ids []string, createdBy map[string]string) (map[string]domain.Sharing, error) {
	personal, err := authz.PersonalConnectionIDs(ctx, s.d.Graph, ids)
	if err != nil {
		return nil, err
	}
	out := make(map[string]domain.Sharing, len(ids))
	for _, id := range ids {
		_, p := personal[id]
		out[id] = domain.Sharing{Personal: p, IsOwner: createdBy[id] == c.UserID}
	}
	return out, nil
}

// SetSharing is set_sharing: only the connection's owner may share it with the
// workspace or take it back; making it personal first lends it to every agent
// whose saved tools name it.
func (s *Service) SetSharing(ctx context.Context, c authn.Caller, id string, shared bool) error {
	owner, err := authz.IsConnectionOwner(ctx, s.d.Graph, c.GraphSubject(), id)
	if err != nil {
		return err
	}
	if !owner {
		return ErrNotConnectionOwner
	}
	w, ok := s.d.Graph.(authz.Writer)
	if !ok {
		return errNoGraphWriter
	}
	if shared {
		return authz.ShareWithWorkspace(ctx, w, id)
	}
	if s.d.Agents == nil {
		return errNoAgents
	}
	agents, err := s.d.Agents.Naming(ctx, c.Workspace, id)
	if err != nil {
		return err
	}
	for _, agentID := range agents {
		if err := authz.LendConnection(ctx, w, id, agentID); err != nil {
			return err
		}
	}
	return authz.MakePersonal(ctx, w, id)
}
