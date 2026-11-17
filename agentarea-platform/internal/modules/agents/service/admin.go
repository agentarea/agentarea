package service

import "context"

// RequireAdmin is require_workspace_admin for the caller in ctx (the edge's
// admin authority, rendered by the edge's error mapper).
func (s *Service) RequireAdmin(ctx context.Context) error {
	if s.d.Admin == nil {
		return &UnwiredError{Feature: "workspace admin authority"}
	}
	return s.d.Admin(ctx)
}
