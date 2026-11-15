package service

import (
	"context"
	"errors"

	sandboxapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
)

// ValidateArtifacts is the completion barrier: the declared sandbox files are
// persisted into the workspace artifacts and checked; the verdict fails closed.
func (s *Service) ValidateArtifacts(ctx context.Context, p Principal, taskID string, paths []string) (sandboxapi.ArtifactValidation, error) {
	if _, err := workspace(p); err != nil {
		return sandboxapi.ArtifactValidation{}, err
	}
	if s.d.Runtime == nil {
		return sandboxapi.ArtifactValidation{}, errors.New("validating artifacts needs the sandbox runtime")
	}
	v, err := s.d.Runtime.ValidateArtifacts(ctx, p.WorkspaceID, taskID, paths)
	if err != nil {
		return sandboxapi.ArtifactValidation{}, err
	}
	switch v.State {
	case "passed", "failed", "unavailable":
	default:
		v.State = "unavailable"
	}
	if v.State == "passed" && len(v.Issues) > 0 {
		v.State = "failed"
	}
	return v, nil
}
