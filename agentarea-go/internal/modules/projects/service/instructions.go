package service

import (
	"context"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/projects/api"
)

var _ api.RunInstructions = (*Service)(nil)

// Chain is run_instructions, in one read session.
func (s *Service) Chain(ctx context.Context, ws scope.Workspace, agentID, projectID string) ([]api.Instruction, error) {
	var current *uuid.UUID
	if projectID != "" {
		id, err := uuid.Parse(projectID)
		if err != nil {
			return nil, api.ErrInvalidProject
		}
		current = &id
	}
	var chain []api.Instruction
	err := s.read(ctx, ws, func(sess db.Session) error {
		if current == nil {
			agent, err := uuid.Parse(agentID)
			if err != nil {
				return nil
			}
			ids, err := s.d.Store.AgentProjects(ctx, sess, agent)
			if err != nil || len(ids) != 1 {
				return err
			}
			current = &ids[0]
		}
		seen := map[uuid.UUID]bool{}
		for current != nil && !seen[*current] {
			seen[*current] = true
			n, ok, err := s.d.Store.Node(ctx, sess, *current)
			if err != nil || !ok {
				return err
			}
			if n.Instructions != nil && strings.TrimSpace(*n.Instructions) != "" {
				chain = append(chain, api.Instruction{Name: n.Name, Text: strings.TrimSpace(*n.Instructions)})
			}
			current = nil
			if n.ParentProjectID != nil {
				next, err := uuid.Parse(*n.ParentProjectID)
				if err != nil {
					return err
				}
				current = &next
			}
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	for i, j := 0, len(chain)-1; i < j; i, j = i+1, j-1 {
		chain[i], chain[j] = chain[j], chain[i]
	}
	return chain, nil
}

// Blocks is Chain rendered as _with_project_instructions quotes each project
// (the name escaped as html.escape does).
func (s *Service) Blocks(ctx context.Context, ws scope.Workspace, agentID, projectID string) ([]string, error) {
	chain, err := s.Chain(ctx, ws, agentID, projectID)
	if err != nil {
		return nil, err
	}
	attr := strings.NewReplacer("&", "&amp;", "<", "&lt;", ">", "&gt;", "\"", "&quot;", "'", "&#x27;")
	out := make([]string, len(chain))
	for i, p := range chain {
		out[i] = "<project name=\"" + attr.Replace(p.Name) + "\">\n" + p.Text + "\n</project>"
	}
	return out, nil
}
