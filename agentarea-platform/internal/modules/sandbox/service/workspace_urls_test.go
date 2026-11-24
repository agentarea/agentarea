package service

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

func TestDownloadURLsSignOnlyTheTasksObjects(t *testing.T) {
	f := newFixture(t, Deps{})
	ctx := context.Background()
	w := f.svc.TaskWorkspace()
	if _, err := w.PutFiles(ctx, wsID, "task", []api.WorkspaceFile{
		{Path: "inputs/attachments/IMG.MOV", Data: []byte("movie")},
		{Path: "inputs/photos/a.jpg", Data: []byte("a")},
		{Path: "inputs/photos/b.jpg", Data: []byte("b")},
		{Path: "inputs/photosets.txt", Data: []byte("not under the folder")},
	}, api.WriteOptions{}); err != nil {
		t.Fatal(err)
	}
	objects := "https://s3.test/workspaces/" + wsID + "/tasks/task/objects/"
	urls, err := w.DownloadURLs(ctx, wsID, "task", "inputs/attachments/IMG.MOV", 5*time.Minute)
	if err != nil || len(urls) != 1 || urls[0].Path != "inputs/attachments/IMG.MOV" || urls[0].URL != objects+sha("movie") ||
		urls[0].SHA256 != sha("movie") || urls[0].Size != 5 {
		t.Fatalf("file: %+v %v", urls, err)
	}
	urls, err = w.DownloadURLs(ctx, wsID, "task", "inputs/photos/", 5*time.Minute)
	if err != nil || len(urls) != 2 || urls[0].Path != "inputs/photos/a.jpg" || urls[1].URL != objects+sha("b") {
		t.Fatalf("folder: %+v %v", urls, err)
	}
	if _, err := w.DownloadURLs(ctx, wsID, "task", "inputs/none", time.Minute); !errors.Is(err, api.ErrFileNotFound) {
		t.Fatalf("missing: %v", err)
	}
	if _, err := w.DownloadURLs(ctx, wsID, "task", "../other/objects", time.Minute); err == nil {
		t.Fatal("a path out of the task was signed")
	}
}
