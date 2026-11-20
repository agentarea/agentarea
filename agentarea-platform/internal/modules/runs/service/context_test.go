package service

import (
	"context"
	"io"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

type taskFiles struct {
	sandboxapi.TaskWorkspace
	files map[string][]byte
	asked []string
}

func (w *taskFiles) Get(_ context.Context, workspaceID, taskID, path string) ([]byte, string, error) {
	key := workspaceID + "/" + taskID + "/" + path
	w.asked = append(w.asked, key)
	data, ok := w.files[key]
	if !ok {
		return nil, "", sandboxapi.ErrFileNotFound
	}
	return data, "application/json", nil
}

type askedBlob struct {
	*memBlob
	asked []string
}

func (b *askedBlob) Get(ctx context.Context, key string) (io.ReadCloser, blob.Info, error) {
	b.asked = append(b.asked, key)
	return b.memBlob.Get(ctx, key)
}

const triggerEventInput = "inputs/attachments/trigger-event.json"

func TestTheTriggerEventInputIsReadableWithoutASandbox(t *testing.T) {
	p := testPrincipal()
	event := "{\n  \"action\": \"opened\",\n  \"pull_request\": {\n    \"number\": 42\n  }\n}"
	ws := &taskFiles{files: map[string][]byte{p.WorkspaceID + "/t1/" + triggerEventInput: []byte(event)}}
	s := New(Deps{Blob: newMemBlob(), Workspace: ws, Log: quiet()})
	got, err := s.ReadOutput(context.Background(), p, "t1", triggerEventInput, "", nil, nil)
	if err != nil || got != event {
		t.Fatalf("read %q %v", got, err)
	}
	got, err = s.ReadOutput(context.Background(), p, "t1", triggerEventInput, "number", nil, nil)
	if err != nil || strings.TrimSpace(got) != "\"number\": 42" {
		t.Fatalf("grep %q %v", got, err)
	}
	got, err = s.ReadOutput(context.Background(), p, "t1", triggerEventInput, "", intp(2), nil)
	if err != nil || got != "{\n  \"action\": \"opened\"," {
		t.Fatalf("head %q %v", got, err)
	}
}

func TestReadOutputStaysInsideTheTasksInputsAndOutputs(t *testing.T) {
	p := testPrincipal()
	ws := &taskFiles{files: map[string][]byte{
		p.WorkspaceID + "/t2/" + triggerEventInput: []byte("{}"),
		p.WorkspaceID + "/t1/workspace.txt":        []byte("x"),
		p.WorkspaceID + "/t1/inputs/attachments/x": []byte("x"),
	}}
	store := &askedBlob{memBlob: newMemBlob()}
	s := New(Deps{Blob: store, Workspace: ws, Log: quiet()})
	if err := s.StoreOutput(context.Background(), p, "t2", "o1", "other task"); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{
		"../t2/outputs/o1", "../../t2/outputs/o1", "/etc/passwd", "..", ".", "",
		"workspace.txt", "inputs/x", "inputs/attachments/", "inputs/attachments/..", "inputs/attachments/.",
		"inputs/attachments/../../t2/" + triggerEventInput, "inputs/attachments/sub/x", "inputs/attachments/x\n",
		"./" + triggerEventInput, "inputs\\attachments\\x", "outputs/o1", "o1\\..\\x",
	} {
		if got, err := s.ReadOutput(context.Background(), p, "t1", name, "", nil, nil); err == nil {
			t.Errorf("%q was read: %q", name, got)
		}
	}
	if _, err := s.ReadOutput(context.Background(), p, "t1", triggerEventInput, "", nil, nil); err == nil || !strings.Contains(err.Error(), "no task input file") {
		t.Errorf("another task's input was read: %v", err)
	}
	if _, err := s.ReadOutput(context.Background(), p, "t1", "o1", "", nil, nil); err == nil || !strings.Contains(err.Error(), "no stored output") {
		t.Errorf("another task's output was read: %v", err)
	}
	for _, key := range ws.asked {
		if name, ok := strings.CutPrefix(key, p.WorkspaceID+"/t1/inputs/attachments/"); !ok || strings.Contains(name, "/") {
			t.Errorf("task workspace asked for %q", key)
		}
	}
	for _, key := range store.asked {
		if name, ok := strings.CutPrefix(key, "tasks/"+p.WorkspaceID+"/t1/outputs/"); !ok || strings.Contains(name, "/") {
			t.Errorf("blob store asked for %q", key)
		}
	}
}

func TestABinaryTaskInputIsRefused(t *testing.T) {
	p := testPrincipal()
	ws := &taskFiles{files: map[string][]byte{p.WorkspaceID + "/t1/inputs/attachments/a.png": {0x89, 'P', 'N', 'G', 0xff, 0xfe}}}
	s := New(Deps{Blob: newMemBlob(), Workspace: ws, Log: quiet()})
	if _, err := s.ReadOutput(context.Background(), p, "t1", "inputs/attachments/a.png", "", nil, nil); err == nil || !strings.Contains(err.Error(), "is not text") {
		t.Fatalf("binary input: %v", err)
	}
}
