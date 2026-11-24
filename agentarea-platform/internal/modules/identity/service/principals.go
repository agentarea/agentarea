package service

import (
	"context"
	"slices"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
)

// Principal kinds (PrincipalType).
const (
	PrincipalUser     = "user"
	PrincipalAgent    = "agent"
	PrincipalPlatform = "platform"
)

// MaxPrincipalIDs caps one resolve (MAX_IDS).
const MaxPrincipalIDs = 200

// PrincipalView is PrincipalResponse.
type PrincipalView struct {
	ID          string
	Type        string
	DisplayName *string
	Email       *string
}

func reservedPrincipal(id string) bool { return id == "platform" || id == "system" }

// ResolvePrincipals is resolve_principals: reserved ids, then the
// workspace's agents (archived and harness ones too), then the directory.
// Ids nothing resolves are left out.
func (s *Service) ResolvePrincipals(ctx context.Context, c authn.Caller, ids []string) ([]PrincipalView, error) {
	var unique []string
	for _, id := range ids {
		if id != "" && !slices.Contains(unique, id) {
			unique = append(unique, id)
		}
	}
	if len(unique) > MaxPrincipalIDs {
		unique = unique[:MaxPrincipalIDs]
	}
	var candidates []string
	for _, id := range unique {
		if !reservedPrincipal(id) {
			candidates = append(candidates, id)
		}
	}
	agentNames := map[string]string{}
	if len(candidates) > 0 {
		var err error
		if agentNames, err = s.d.Agents.AgentNames(ctx, c.Workspace, candidates); err != nil {
			return nil, err
		}
	}
	var lookups []string
	for _, id := range candidates {
		if _, ok := agentNames[id]; !ok {
			lookups = append(lookups, id)
		}
	}
	known, err := s.identities(ctx, lookups)
	if err != nil {
		return nil, err
	}
	var email *string
	if c.Email != "" {
		email = &c.Email
	}
	out := []PrincipalView{}
	for _, id := range unique {
		if reservedPrincipal(id) {
			out = append(out, PrincipalView{ID: id, Type: PrincipalPlatform})
			continue
		}
		if name, ok := agentNames[id]; ok {
			out = append(out, PrincipalView{ID: id, Type: PrincipalAgent, DisplayName: &name})
			continue
		}
		rec := domain.IdentityFor(id, known, c.UserID, email)
		if rec.DisplayName == nil && rec.Email == nil {
			continue
		}
		out = append(out, PrincipalView{ID: id, Type: PrincipalUser, DisplayName: rec.DisplayName, Email: rec.Email})
	}
	return out, nil
}
