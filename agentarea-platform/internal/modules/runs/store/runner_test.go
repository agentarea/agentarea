package store

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestRunnerTaskReadsTheRunnersFieldsInTheWorkspace(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := workspace(t, pool), workspace(t, pool)
	var r Runs
	id, agent := uuid.NewString(), uuid.NewString()
	if err := r.CreateTask(ctx, s, NewTask{
		ID: id, AgentID: agent, Description: "d", Status: "running", CreatedBy: "creator", OriginType: "agent",
		Parameters: map[string]any{"model": "gpt-5"}, Metadata: map[string]any{"runner_client_id": "c1"},
		SourceIdentity: "user:u1",
	}, time.Now()); err != nil {
		t.Fatal(err)
	}
	task, err := r.RunnerTask(ctx, s, id)
	if err != nil {
		t.Fatal(err)
	}
	if task.ID != id || task.AgentID != agent || task.CreatedBy != "creator" || task.SourceIdentity != "user:u1" ||
		task.Parameters["model"] != "gpt-5" || task.Metadata["runner_client_id"] != "c1" {
		t.Fatalf("task: %+v", task)
	}
	if _, err := r.RunnerTask(ctx, other, id); !errors.Is(err, ErrTaskNotFound) {
		t.Fatalf("another workspace reads the task: %v", err)
	}
}

func TestSetRunnerSessionKeepsTheRestOfTheMetadata(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := workspace(t, pool), workspace(t, pool)
	var r Runs
	task := newTask(t, s)
	if ok, err := r.SetRunnerSession(ctx, other, task.ID, "sess-1", time.Now()); err != nil || ok {
		t.Fatalf("another workspace wrote the session: %v %v", ok, err)
	}
	if ok, err := r.SetRunnerSession(ctx, s, task.ID, "sess-1", time.Now()); err != nil || !ok {
		t.Fatalf("first write: %v %v", ok, err)
	}
	if ok, err := r.SetRunnerSession(ctx, s, task.ID, "sess-1", time.Now()); err != nil || ok {
		t.Fatalf("the same session wrote again: %v %v", ok, err)
	}
	got, err := r.RunnerTask(ctx, s, task.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got.Metadata["runner_session_id"] != "sess-1" || got.Metadata["a"] != 1.0 {
		t.Fatalf("metadata: %v", got.Metadata)
	}
}
