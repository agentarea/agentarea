package service

import (
	"context"
	"math"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// IDs is every project id of the workspace.
func (s *Service) IDs(ctx context.Context, ws scope.Workspace) ([]string, error) {
	var ids []string
	err := s.read(ctx, ws, func(sess db.Session) error {
		ps, err := s.d.Store.List(ctx, sess, math.MaxInt32, 0)
		for _, p := range ps {
			ids = append(ids, p.ID)
		}
		return err
	})
	return ids, err
}
