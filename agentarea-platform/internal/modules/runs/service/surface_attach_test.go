package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

// attachStore is a task workspace in memory: path → content digest per task.
type attachStore struct {
	sandboxapi.TaskWorkspace
	files    map[string]map[string][]byte
	attached []string
}

func (f *attachStore) AttachObject(_ context.Context, _, taskID, path string, src sandboxapi.AttachSource, _ sandboxapi.WriteOptions) (sandboxapi.ManifestRef, error) {
	if f.files[taskID] == nil {
		f.files[taskID] = map[string][]byte{}
	}
	f.files[taskID][path] = []byte(src.Key)
	f.attached = append(f.attached, taskID+":"+path)
	return sandboxapi.ManifestRef{}, nil
}

func (f *attachStore) Digest(_ context.Context, _, taskID, path string) (string, error) {
	data, ok := f.files[taskID][path]
	if !ok {
		return "", sandboxapi.ErrFileNotFound
	}
	return digestOf(string(data)), nil
}

type signalled struct {
	closedExecutor
	messages []string
}

func (s *signalled) Signal(_ context.Context, _, _ string, args ...any) error {
	s.signals++
	if c, ok := args[0].(api.WorkflowCommandSignal); ok {
		m, _ := c.Payload["message"].(string)
		s.messages = append(s.messages, m)
	}
	return nil
}

func digestOf(key string) string {
	sum := sha256.Sum256([]byte(key))
	return hex.EncodeToString(sum[:])
}

func TestSubmitAttachesAnEventsFilesToItsTaskAndNamesThemInAFollowUp(t *testing.T) {
	s, p, _, l, _, ctx := createSurface(t)
	files := &attachStore{files: map[string]map[string][]byte{}}
	x := &signalled{}
	s.d.Workspaces, s.d.Executor = files, x
	ws, _ := scope.NewWorkspace(p.WorkspaceID, "")
	params := map[string]any{"trigger_id": "trg", "session": map[string]any{"continue": true, "key": "chat-1"}}
	video := api.TaskAttachment{Key: "events/s/e1/0-IMG.MOV", Name: "IMG.MOV", SHA256: digestOf("events/s/e1/0-IMG.MOV"), Size: 20155031, ContentType: "video/quicktime"}
	first, err := s.Submit(ctx, ws, api.TaskRequest{AgentID: p.AgentID, Description: "(file: IMG.MOV)", Parameters: params, UserID: p.UserID,
		Attachments: []api.TaskAttachment{video}})
	if err != nil || first.Routed || len(l.launched) != 1 {
		t.Fatalf("%+v %v", first, err)
	}
	if got := files.attached; len(got) != 1 || got[0] != first.TaskID+":inputs/attachments/IMG.MOV" {
		t.Fatalf("attached %v", got)
	}
	tk, _, err := s.loadTask(ctx, ws, first.TaskID)
	if err != nil {
		t.Fatal(err)
	}
	listed, _ := tk.Metadata.Get("workspace_attachments")
	if l, ok := listed.([]any); !ok || len(l) != 1 || !strings.Contains(fmt.Sprint(l[0]), "inputs/attachments/IMG.MOV") {
		t.Fatalf("the task's prompt does not list the file: %#v", listed)
	}

	again := api.TaskAttachment{Key: "events/s/e2/0-IMG.MOV", Name: "IMG.MOV", SHA256: digestOf("events/s/e2/0-IMG.MOV"), Size: 1 << 20, ContentType: "video/quicktime"}
	next, err := s.Submit(ctx, ws, api.TaskRequest{AgentID: p.AgentID, Description: "Сделай субтитры.", Parameters: params, UserID: p.UserID,
		Attachments: []api.TaskAttachment{again}})
	if err != nil || !next.Routed || next.TaskID != first.TaskID {
		t.Fatalf("%+v %v", next, err)
	}
	if len(x.messages) != 1 || !strings.HasPrefix(x.messages[0], "Сделай субтитры.\n\nAttached file: inputs/attachments/IMG-1.MOV (video/quicktime, 1.0 MB)") {
		t.Fatalf("a file under a taken name must not replace it, and the follow-up names where it went: %q", x.messages)
	}
	if _, ok := files.files[first.TaskID]["inputs/attachments/IMG.MOV"]; !ok {
		t.Fatal("the first file is gone")
	}
}
