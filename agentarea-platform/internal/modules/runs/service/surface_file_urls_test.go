package service

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

type signingStore struct {
	sandboxapi.TaskWorkspace
	signed []string
	ttl    time.Duration
}

func (s *signingStore) DownloadURLs(_ context.Context, _, taskID, path string, ttl time.Duration) ([]sandboxapi.FileURL, error) {
	s.signed, s.ttl = append(s.signed, taskID+":"+path), ttl
	if path != "inputs/attachments/IMG.MOV" {
		return nil, sandboxapi.ErrFileNotFound
	}
	return []sandboxapi.FileURL{{Path: path, URL: "https://s3.test/x", SHA256: "ab", Size: 5}}, nil
}

func TestASubtasksTurnDownloadsItsParentsFiles(t *testing.T) {
	s, p, _, _, _, _ := createSurface(t)
	signer := &signingStore{}
	s.d.Workspaces = signer
	ws, _ := scope.NewWorkspace(p.WorkspaceID, "ws")
	parent, child := uuid.NewString(), uuid.NewString()
	if err := s.d.DB.Write(context.Background(), ws, func(ctx context.Context, tx db.Session) error {
		for id, meta := range map[string]map[string]any{parent: {}, child: {WorkspaceTaskKey: parent}} {
			if err := (store.Runs{}).CreateTask(ctx, tx, store.NewTask{ID: id, AgentID: p.AgentID, Description: "d", Status: "running",
				CreatedBy: p.UserID, Metadata: meta}, time.Now()); err != nil {
				return err
			}
		}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	urls, err := s.TaskFileURLs(context.Background(), ws, child, "inputs/attachments/IMG.MOV")
	if err != nil || len(urls) != 1 || urls[0].URL != "https://s3.test/x" || urls[0].ExpiresInSeconds != 300 {
		t.Fatalf("urls %+v %v", urls, err)
	}
	if signer.signed[0] != parent+":inputs/attachments/IMG.MOV" || signer.ttl != 5*time.Minute {
		t.Fatalf("signed %v for %s", signer.signed, signer.ttl)
	}
	if _, err := s.TaskFileURLs(context.Background(), ws, parent, "inputs/none"); !errors.Is(err, api.ErrNoTaskFile) || signer.signed[1] != parent+":inputs/none" {
		t.Fatalf("own task, missing file: %v %v", err, signer.signed)
	}
}
