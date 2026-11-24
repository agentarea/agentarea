package service

import (
	"context"
	"errors"
	"fmt"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

// SkillActivation asks for a skill's entry at the seq and event id the workflow reserved.
type SkillActivation struct {
	TaskID, ExecutionID, ToolCallID string
	// FilesTaskID is the task whose files the run works on, when not its own (a subtask's parent).
	FilesTaskID string
	// WorkflowID owns the workspace lease the skill's files are written under.
	WorkflowID string
	Skill      api.Skill
	Seq        int64
	EventID    string
	Iteration  *int
	MaxTokens  int
}

// SkillActivated is the entry's size, never its text.
type SkillActivated struct {
	Chars, EstTokens int
	Summarized       bool
	URLs             []string
}

// ActivateSkill puts a skill's SKILL.md into the task log, never into history
// (files.py activate_skill_activity). Only an unreachable service is retried.
func (s *Service) ActivateSkill(ctx context.Context, p Principal, in SkillActivation) (_ SkillActivated, err error) {
	call := s.d.ToolMetrics.begin(ctx, toolKindSkill, toolPathWorker)
	defer func() {
		call.set(skillOutcome(err))
		call.end(ctx, err)
	}()
	ws, err := workspace(p)
	if err != nil {
		return SkillActivated{}, err
	}
	out, err := s.activateSkill(ctx, p, ws, in)
	var app *durable.ApplicationError
	var unreachable *UnreachableError
	if !errors.As(err, &app) && errors.As(err, &unreachable) {
		return SkillActivated{}, &durable.ApplicationError{
			Type: "ServiceUnreachable", Message: unreachable.Error(),
			Details: []any{map[string]any{"service": unreachable.Service}}, Cause: err,
		}
	}
	return out, err
}

func (s *Service) activateSkill(ctx context.Context, p Principal, ws scope.Workspace, in SkillActivation) (SkillActivated, error) {
	name := in.Skill.Name
	if s.d.Skills == nil {
		return SkillActivated{}, errors.New("activating a skill needs the skill packages port")
	}
	switch err := s.d.Skills.Allow(ctx, p, in.Skill); {
	case errors.Is(err, ErrRefused):
		return SkillActivated{}, nonRetryable("SkillActivationRefused", fmt.Sprintf("Skill '%s' cannot be activated: %v", name, err), err)
	case errors.Is(err, ErrNotFound):
		return SkillActivated{}, nonRetryable("SkillNotFound", fmt.Sprintf("Skill '%s' no longer exists", name), err)
	case err != nil:
		return SkillActivated{}, s.skillFailure(name, err)
	}
	body, err := s.d.Skills.ReadSkillMD(ctx, p, in.Skill)
	switch {
	case errors.Is(err, ErrRefused) || errors.Is(err, ErrNotFound):
		return SkillActivated{}, nonRetryable("SkillUnreadable", fmt.Sprintf("Skill '%s' cannot be read: %v", name, err), err)
	case err != nil:
		return SkillActivated{}, s.skillFailure(name, err)
	}
	directory, paths, err := s.putSkillFiles(ctx, p, in)
	if err != nil {
		s.d.Log.WarnContext(ctx, "could not put the skill's files in the sandbox", "skill", name, "error", err)
		directory, paths = "", nil
	}
	pointer := fmt.Sprintf("Read it with read_tool_output(\"%s\"), or search it with read_tool_output(\"%s\", grep=\"pattern\").", in.ToolCallID, in.ToolCallID)
	if directory != "" {
		pointer = fmt.Sprintf("Read it in full from %s/SKILL.md with the shell tool, e.g. bash(\"cat %s/SKILL.md\").", directory, directory)
	}
	content, summarized := domain.SkillEntry(name, body, in.MaxTokens, directory, paths, pointer)
	if summarized && directory == "" {
		if err := s.putText(ctx, domain.OutputKey(p.WorkspaceID, in.TaskID, in.ToolCallID), body, "application/json"); err != nil {
			return SkillActivated{}, s.skillFailure(name, &UnreachableError{Service: "Object storage", Err: err})
		}
	}
	entry := domain.Entry{
		Seq: in.Seq, EventID: in.EventID, Kind: domain.KindMessage, Role: "tool", Content: content,
		ToolCallID: in.ToolCallID, Name: domain.ToolActivateSkill, Iteration: in.Iteration, ExecutionID: in.ExecutionID,
	}
	rows, err := s.offloadBodies(ctx, p.WorkspaceID, in.TaskID, []domain.Entry{entry})
	if err != nil {
		return SkillActivated{}, s.skillFailure(name, &UnreachableError{Service: "Object storage", Err: err})
	}
	err = s.d.DB.Write(ctx, ws, func(ctx context.Context, tx db.Session) error {
		task, err := s.store.Task(ctx, tx, in.TaskID)
		if err != nil {
			return err
		}
		return s.store.InsertEntry(ctx, tx, task, rows[0], p.UserID)
	})
	if err != nil {
		return SkillActivated{}, recordFailure(err)
	}
	urls := domain.ExternalURLs([]domain.Entry{{Role: "tool", Content: body}})
	if len(urls) > domain.SeenURLsLimit {
		urls = urls[:domain.SeenURLsLimit]
	}
	return SkillActivated{
		Chars: len([]rune(content)), EstTokens: domain.EstimateTokens(content) + domain.TokensPerMessage,
		Summarized: summarized, URLs: urls,
	}, nil
}

// skillFailure: an unreachable service is retried through the outage; anything else is final.
func (s *Service) skillFailure(name string, err error) error {
	var unreachable *UnreachableError
	if errors.As(err, &unreachable) {
		return err
	}
	return nonRetryable("SkillActivationFailed", fmt.Sprintf("Skill '%s' could not be activated: %v", name, err), err)
}

// putSkillFiles copies the skill's package into the task workspace under its
// directory (files.py _put_skill_files); the paths are the workspace's.
func (s *Service) putSkillFiles(ctx context.Context, p Principal, in SkillActivation) (string, []string, error) {
	if s.d.Workspace == nil {
		return "", nil, errors.New("putting a skill's files needs the task workspace")
	}
	if p.WorkspaceID == "" || in.TaskID == "" {
		return "", nil, errors.New("workspace_id and task_id are required for skill materialization")
	}
	pkg, err := s.d.Skills.Files(ctx, p, in.Skill)
	if err != nil {
		return "", nil, err
	}
	files := make([]domain.SkillFile, len(pkg))
	for i, f := range pkg {
		files[i] = domain.SkillFile(f)
	}
	laid, err := domain.SkillWorkspaceFiles(in.Skill.Name, in.Skill.ID, files)
	if err != nil {
		return "", nil, err
	}
	put := make([]sandboxapi.WorkspaceFile, len(laid))
	paths := make([]string, len(laid))
	for i, f := range laid {
		put[i] = sandboxapi.WorkspaceFile{Path: f.Path, Data: f.Data}
		paths[i] = f.Path
	}
	actor := &sandboxapi.Actor{UserID: p.UserID, ActorType: "agent"}
	if p.AgentID != "" {
		actor.AgentID = &p.AgentID
	}
	actor.TaskID = &in.TaskID
	filesTask := in.TaskID
	if in.FilesTaskID != "" {
		filesTask = in.FilesTaskID
	}
	if _, err := s.d.Workspace.PutFiles(ctx, p.WorkspaceID, filesTask, put, sandboxapi.WriteOptions{Owner: in.WorkflowID, Actor: actor}); err != nil {
		return "", nil, err
	}
	return domain.SkillWorkspaceDir(in.Skill.Name, in.Skill.ID), paths, nil
}
