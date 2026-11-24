package api

import (
	"context"
	"errors"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

// ErrSkillRefused: the skill exists but this run may not use or read it.
var ErrSkillRefused = errors.New("skill refused")

// SkillUnreachableError: a store a skill read needs did not answer.
type SkillUnreachableError struct {
	Service string
	Err     error
}

func (e *SkillUnreachableError) Error() string {
	return e.Service + " is unreachable: " + e.Err.Error()
}
func (e *SkillUnreachableError) Unwrap() error { return e.Err }

// SkillPackageFile is one file of a skill's package, by its path in the package.
type SkillPackageFile struct {
	Path string
	Data []byte
}

// RunSkills is what a run reads of skills (config.py _resolve_task_resources,
// _runnable_skills; files.py activate_skill_activity). A missing skill is
// ErrSkillNotFound, a refusal ErrSkillRefused, an outage *SkillUnreachableError.
type RunSkills interface {
	// Offered are the agent's skills plus the ones the run selected, less
	// those the install policy withholds, which are listed with the reason.
	Offered(ctx context.Context, ws scope.Workspace, agentID string, selected []string) ([]runsapi.Skill, []runsapi.WithheldSkill, error)
	// Allow is the install policy's say over activating the skill now.
	Allow(ctx context.Context, ws scope.Workspace, skill runsapi.Skill) error
	// ReadSkillMD is the SKILL.md of the package the run was configured with.
	ReadSkillMD(ctx context.Context, ws scope.Workspace, skill runsapi.Skill) (string, error)
	// PackageFiles is every file of that package.
	PackageFiles(ctx context.Context, ws scope.Workspace, skill runsapi.Skill) ([]SkillPackageFile, error)
}
