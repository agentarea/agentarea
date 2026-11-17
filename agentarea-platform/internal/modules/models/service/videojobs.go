package service

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/store"
)

// VideoJobStore is the video_generation_jobs table (store.VideoJobs).
type VideoJobStore interface {
	Create(ctx context.Context, s db.Session, j store.NewVideoJob, now time.Time) error
	OfTask(ctx context.Context, s db.Session, id uuid.UUID, taskID string) (store.VideoJob, bool, error)
	SetStatus(ctx context.Context, s db.Session, id uuid.UUID, status, errText string, now time.Time) error
	RecordSaved(ctx context.Context, s db.Session, id uuid.UUID, v store.SavedVideo, now time.Time) (bool, error)
}

var _ api.VideoJobs = (*Service)(nil)

func (s *Service) videoJobs() (VideoJobStore, error) {
	if s.d.VideoJobs == nil {
		return nil, fmt.Errorf("video jobs are not wired")
	}
	return s.d.VideoJobs, nil
}

// CreateVideoJob records a submitted generation of a task.
func (s *Service) CreateVideoJob(ctx context.Context, ws scope.Workspace, userID string, j api.NewVideoJob) (string, error) {
	jobs, err := s.videoJobs()
	if err != nil {
		return "", err
	}
	model, err := uuid.Parse(j.ModelInstanceID)
	if err != nil {
		return "", fmt.Errorf("video job model instance %q: %w", j.ModelInstanceID, err)
	}
	if j.TaskID == "" {
		return "", fmt.Errorf("a video job belongs to a task")
	}
	id := uuid.New()
	err = s.d.DB.Write(ctx, ws, func(ctx context.Context, tx db.Session) error {
		return jobs.Create(ctx, tx, store.NewVideoJob{
			ID: id, ModelInstanceID: model, CreatedBy: userID, TaskID: j.TaskID, ProviderJobID: j.ProviderJobID,
			Prompt: j.Prompt, Status: j.Status, Funding: j.Funding,
		}, s.d.Now())
	})
	return id.String(), err
}

// VideoJobOfTask is the job when the workspace's task submitted it (get_for_task).
func (s *Service) VideoJobOfTask(ctx context.Context, ws scope.Workspace, jobID, taskID string) (api.VideoJob, bool, error) {
	jobs, err := s.videoJobs()
	if err != nil {
		return api.VideoJob{}, false, err
	}
	id, err := uuid.Parse(jobID)
	if err != nil {
		return api.VideoJob{}, false, nil
	}
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return api.VideoJob{}, false, err
	}
	defer release()
	j, ok, err := jobs.OfTask(ctx, sess, id, taskID)
	if err != nil || !ok {
		return api.VideoJob{}, false, err
	}
	return api.VideoJob{
		ID: j.ID.String(), ModelInstanceID: j.ModelInstanceID.String(), ProviderJobID: j.ProviderJobID, Status: j.Status,
		Error: j.Error, FilePath: j.FilePath, BilledCallRef: j.BilledCallRef, Funding: j.Funding, Billing: j.Billing,
	}, true, nil
}

// SetVideoJobStatus records where the provider says the job stands.
func (s *Service) SetVideoJobStatus(ctx context.Context, ws scope.Workspace, jobID, status, errText string) error {
	jobs, err := s.videoJobs()
	if err != nil {
		return err
	}
	id, err := uuid.Parse(jobID)
	if err != nil {
		return err
	}
	return s.d.DB.Write(ctx, ws, func(ctx context.Context, tx db.Session) error {
		return jobs.SetStatus(ctx, tx, id, status, errText, s.d.Now())
	})
}

// RecordVideoSaved is record_saved: the finished video and the call that bills it, once.
func (s *Service) RecordVideoSaved(ctx context.Context, ws scope.Workspace, jobID string, v api.SavedVideo) (bool, error) {
	jobs, err := s.videoJobs()
	if err != nil {
		return false, err
	}
	id, err := uuid.Parse(jobID)
	if err != nil {
		return false, err
	}
	var billed bool
	err = s.d.DB.Write(ctx, ws, func(ctx context.Context, tx db.Session) error {
		billed, err = jobs.RecordSaved(ctx, tx, id, store.SavedVideo{
			FilePath: v.FilePath, CostUSD: v.CostUSD, BilledCost: v.BilledCost, Billing: v.Billing, CallRef: v.CallRef,
		}, s.d.Now())
		return err
	})
	return billed, err
}
