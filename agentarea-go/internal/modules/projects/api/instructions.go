package api

import (
	"context"
	"errors"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// ErrInvalidProject: the run names a project by something that is no project id.
var ErrInvalidProject = errors.New("run project_id is not a project id")

// Instruction is one project's name and its instructions, trimmed.
type Instruction struct {
	Name string
	Text string
}

// RunInstructions is what a run reads of its project (ProjectService.run_instructions).
type RunInstructions interface {
	// Chain is the instructions of the run's project and each one above it,
	// root first. An empty projectID means the one project the agent belongs
	// to; an agent in several gets none. A project without instructions is
	// skipped; a missing project ends the walk.
	Chain(ctx context.Context, ws scope.Workspace, agentID, projectID string) ([]Instruction, error)
	// Blocks is Chain with each project rendered as the run's prompt quotes it:
	// <project name="...">\ntext\n</project>.
	Blocks(ctx context.Context, ws scope.Workspace, agentID, projectID string) ([]string, error)
}
