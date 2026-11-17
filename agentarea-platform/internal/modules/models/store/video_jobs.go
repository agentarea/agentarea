package store

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
)

// VideoJobs reads and writes video_generation_jobs inside the session's workspace.
type VideoJobs struct{}

// NewVideoJob is a submitted generation; Funding is the hold kept across polls.
type NewVideoJob struct {
	ID, ModelInstanceID   uuid.UUID
	CreatedBy, TaskID     string
	ProviderJobID, Prompt string
	Status                string
	Funding               []byte
}

// VideoJob is a job as a poll reads it.
type VideoJob struct {
	ID, ModelInstanceID            uuid.UUID
	ProviderJobID, Status          string
	BilledCallRef, FilePath, Error string
	Funding, Billing               []byte
}

// SavedVideo is the finished video and the line that bills it.
type SavedVideo struct {
	FilePath            string
	CostUSD, BilledCost *money.Decimal
	Billing             []byte
	CallRef             string
}

// Create writes a job of the session's workspace.
func (VideoJobs) Create(ctx context.Context, s db.Session, j NewVideoJob, now time.Time) error {
	return New(s.Q()).InsertVideoJob(ctx, InsertVideoJobParams{
		ID: j.ID, Now: naive(now), WorkspaceID: s.Workspace().ID(), CreatedBy: j.CreatedBy, ModelInstanceID: j.ModelInstanceID,
		TaskID: j.TaskID, ProviderJobID: j.ProviderJobID, Prompt: j.Prompt, Status: j.Status, Funding: j.Funding,
	})
}

// OfTask is the job when the workspace's task submitted it (get_for_task).
func (VideoJobs) OfTask(ctx context.Context, s db.Session, id uuid.UUID, taskID string) (VideoJob, bool, error) {
	r, err := New(s.Q()).GetVideoJobOfTask(ctx, GetVideoJobOfTaskParams{ID: id, WorkspaceID: s.Workspace().ID(), TaskID: taskID})
	if errors.Is(err, pgx.ErrNoRows) {
		return VideoJob{}, false, nil
	}
	if err != nil {
		return VideoJob{}, false, err
	}
	return VideoJob{
		ID: r.ID, ModelInstanceID: r.ModelInstanceID, ProviderJobID: r.ProviderJobID, Status: r.Status,
		BilledCallRef: r.BilledCallRef.String, FilePath: r.FilePath.String, Error: r.Error.String, Funding: r.Funding, Billing: r.Billing,
	}, true, nil
}

// SetStatus records where the provider says the job stands; an empty errText clears the error.
func (VideoJobs) SetStatus(ctx context.Context, s db.Session, id uuid.UUID, status, errText string, now time.Time) error {
	return New(s.Q()).SetVideoJobStatus(ctx, SetVideoJobStatusParams{
		Status: status, Error: pgtype.Text{String: errText, Valid: errText != ""}, Now: naive(now), ID: id, WorkspaceID: s.Workspace().ID(),
	})
}

// RecordSaved records the finished video and which call bills it, once: true
// when callRef is that call, the first to record it or a retry of it.
func (VideoJobs) RecordSaved(ctx context.Context, s db.Session, id uuid.UUID, v SavedVideo, now time.Time) (bool, error) {
	q := New(s.Q())
	n, err := q.RecordVideoSaved(ctx, RecordVideoSavedParams{
		FilePath: pgtype.Text{String: v.FilePath, Valid: true}, CostUsd: numeric(v.CostUSD), BilledCost: numeric(v.BilledCost),
		Billing: v.Billing, CallRef: pgtype.Text{String: v.CallRef, Valid: true}, Now: naive(now), ID: id, WorkspaceID: s.Workspace().ID(),
	})
	if err != nil {
		return false, err
	}
	if n > 0 {
		return true, nil
	}
	ref, err := q.VideoJobBilledCallRef(ctx, VideoJobBilledCallRefParams{ID: id, WorkspaceID: s.Workspace().ID()})
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	return ref.Valid && ref.String == v.CallRef, nil
}

func numeric(d *money.Decimal) pgtype.Numeric {
	var n pgtype.Numeric
	if d != nil {
		_ = n.Scan(d.Plain())
	}
	return n
}
