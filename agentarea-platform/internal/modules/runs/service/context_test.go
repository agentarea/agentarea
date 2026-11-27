package service

import (
	"bytes"
	"context"
	"image"
	"image/png"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

type taskFiles struct {
	sandboxapi.TaskWorkspace
	files map[string][]byte
	types map[string]string
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

func (w *taskFiles) PutFiles(_ context.Context, workspaceID, taskID string, files []sandboxapi.WorkspaceFile, _ sandboxapi.WriteOptions) (sandboxapi.ManifestRef, error) {
	if w.files == nil {
		w.files, w.types = map[string][]byte{}, map[string]string{}
	}
	for _, f := range files {
		w.files[workspaceID+"/"+taskID+"/"+f.Path] = f.Data
		w.types[workspaceID+"/"+taskID+"/"+f.Path] = f.ContentType
	}
	return sandboxapi.ManifestRef{}, nil
}

const triggerEventInput = "inputs/attachments/trigger-event.json"

func readFileCall(s *Service, args map[string]any, metadata map[string]any) ToolOutput {
	in := ToolCall{TaskID: "t1", ToolName: domain.ToolReadFile, Args: args, RunMetadata: metadata, Binding: domain.ReadFileBinding()}
	out, err := s.dispatch(context.Background(), testPrincipal(), in, nil)
	if err != nil {
		panic(err)
	}
	return out
}

func TestATaskInputIsReadWithoutASandbox(t *testing.T) {
	p := testPrincipal()
	event := "{\n  \"action\": \"opened\",\n  \"pull_request\": {\n    \"number\": 42\n  }\n}"
	ws := &taskFiles{files: map[string][]byte{p.WorkspaceID + "/t1/" + triggerEventInput: []byte(event)}}
	rt := &fakeRuntime{files: map[string][]byte{triggerEventInput: []byte("the sandbox copy")}}
	s := New(Deps{Workspace: ws, Runtime: rt, Log: quiet()})
	if got := readFileCall(s, map[string]any{"path": triggerEventInput}, nil); got.Result != event {
		t.Fatalf("read %q", got.Result)
	}
	if got := readFileCall(s, map[string]any{"path": triggerEventInput, "grep": "NUMBER"}, nil); strings.TrimSpace(got.Result) != "\"number\": 42" {
		t.Fatalf("grep %q", got.Result)
	}
	if got := readFileCall(s, map[string]any{"path": triggerEventInput, "head": float64(2)}, nil); got.Result != "{\n  \"action\": \"opened\"," {
		t.Fatalf("head %q", got.Result)
	}
	if got := readFileCall(s, map[string]any{"path": triggerEventInput, "offset": float64(3), "tail": float64(1)}, nil); got.Result != "}" {
		t.Fatalf("offset and tail %q", got.Result)
	}
	if got := readFileCall(s, map[string]any{"path": "inputs/attachments/gone.json"}, nil); got.Result != "Error: File inputs/attachments/gone.json does not exist" {
		t.Fatalf("missing %q", got.Result)
	}
}

func TestReadFileReadsOtherPathsFromTheSandbox(t *testing.T) {
	p := testPrincipal()
	ws := &taskFiles{files: map[string][]byte{p.WorkspaceID + "/t1/outputs/a.md": []byte("stale")}}
	rt := &fakeRuntime{files: map[string][]byte{"outputs/a.md": []byte(strings.Repeat("y", domain.ReadOutputMaxChars+10))}}
	s := New(Deps{Workspace: ws, Runtime: rt, Log: quiet()})
	got := readFileCall(s, map[string]any{"path": "outputs/a.md"}, nil).Result
	if !strings.HasPrefix(got, strings.Repeat("y", domain.ReadOutputMaxChars)+"\n... [truncated at") {
		t.Fatalf("read %.40q", got)
	}
	if len(ws.asked) != 0 {
		t.Fatalf("the task workspace was asked for %v", ws.asked)
	}
}

func TestReadFileStaysInsideTheTasksInputs(t *testing.T) {
	p := testPrincipal()
	ws := &taskFiles{files: map[string][]byte{
		p.WorkspaceID + "/t2/" + triggerEventInput:       []byte("{}"),
		p.WorkspaceID + "/parent/inputs/tool-outputs/o1": []byte("the parent's"),
	}}
	s := New(Deps{Workspace: ws, Runtime: &fakeRuntime{files: map[string][]byte{}}, Log: quiet()})
	for _, name := range []string{
		"inputs/../../t2/" + triggerEventInput, "inputs/attachments/../../t2/" + triggerEventInput, "/inputs/x", "inputs\\x",
	} {
		if got := readFileCall(s, map[string]any{"path": name}, nil).Result; !strings.HasPrefix(got, "Error reading file: path escapes workspace sandbox") {
			t.Errorf("%q: %q", name, got)
		}
	}
	if got := readFileCall(s, map[string]any{"path": triggerEventInput}, nil).Result; !strings.Contains(got, "does not exist") {
		t.Errorf("another task's input was read: %q", got)
	}
	if got := readFileCall(s, map[string]any{"path": "inputs/tool-outputs/o1"}, map[string]any{WorkspaceTaskKey: "parent"}).Result; got != "the parent's" {
		t.Errorf("a subtask read %q, not its parent's file", got)
	}
	for _, key := range ws.asked {
		if !strings.HasPrefix(key, p.WorkspaceID+"/t1/inputs/") && !strings.HasPrefix(key, p.WorkspaceID+"/parent/inputs/") {
			t.Errorf("task workspace asked for %q", key)
		}
	}
}

func TestReadFileShowsAnImageInputToTheModel(t *testing.T) {
	p := testPrincipal()
	var b bytes.Buffer
	if err := png.Encode(&b, image.NewRGBA(image.Rect(0, 0, 4, 2))); err != nil {
		t.Fatal(err)
	}
	ws := &taskFiles{files: map[string][]byte{
		p.WorkspaceID + "/t1/inputs/attachments/a.png": b.Bytes(),
		p.WorkspaceID + "/t1/inputs/attachments/b.bin": {0xff, 0xfe, 0x00},
	}}
	s := New(Deps{Workspace: ws, Runtime: &fakeRuntime{files: map[string][]byte{}}, Log: quiet()})
	if out := readFileCall(s, map[string]any{"path": "inputs/attachments/a.png"}, nil); len(out.Images) != 1 || !bytes.Equal(out.Images[0].Data, b.Bytes()) {
		t.Fatalf("image %+v", out)
	}
	if out := readFileCall(s, map[string]any{"path": "inputs/attachments/b.bin"}, nil); len(out.Images) != 0 || !strings.Contains(out.Result, "can't decode") {
		t.Fatalf("binary %+v", out)
	}
}

func TestStoreOutputKeepsItAsATaskFile(t *testing.T) {
	p := testPrincipal()
	ws := &taskFiles{}
	s := New(Deps{Workspace: ws, Log: quiet()})
	path, err := s.StoreOutput(context.Background(), p, "t1", "", "wf", "call_1", `{"items": [1]}`)
	if err != nil || path != "inputs/tool-outputs/call_1.json" {
		t.Fatalf("store %q %v", path, err)
	}
	if got := string(ws.files[p.WorkspaceID+"/t1/"+path]); got != `{"items": [1]}` || ws.types[p.WorkspaceID+"/t1/"+path] != "application/json" {
		t.Fatalf("kept %q as %q", got, ws.types[p.WorkspaceID+"/t1/"+path])
	}
	path, err = s.StoreOutput(context.Background(), p, "t1", "parent", "wf", "call_2", "alpha\nbeta")
	if err != nil || path != "inputs/tool-outputs/call_2.txt" || string(ws.files[p.WorkspaceID+"/parent/"+path]) != "alpha\nbeta" {
		t.Fatalf("a subtask's output %q %v: %v", path, err, ws.files)
	}
	for _, id := range []string{"", "..", "a/b", `a\b`} {
		if _, err := s.StoreOutput(context.Background(), p, "t1", "", "wf", id, "x"); err == nil {
			t.Errorf("output id %q was kept", id)
		}
	}
	if _, err := s.StoreOutput(context.Background(), Principal{}, "t1", "", "wf", "o1", "x"); appErr(t, err).Type != "ValueError" {
		t.Fatal("an incomplete principal was accepted")
	}
}

func TestReadFileOutputIsNeverOffloaded(t *testing.T) {
	p := testPrincipal()
	big := strings.Repeat("z\n", domain.OutputOffloadChars)
	ws := &taskFiles{files: map[string][]byte{p.WorkspaceID + "/t1/inputs/tool-outputs/o1.txt": []byte(big)}}
	s := New(Deps{Blob: newMemBlob(), Workspace: ws, Runtime: &fakeRuntime{files: map[string][]byte{}}, Pricing: eurPricing{}, Log: quiet()})
	out, err := s.ExecuteTool(context.Background(), p, ToolCall{
		TaskID: "t1", ToolCallID: "c1", ToolName: domain.ToolReadFile, ActivityID: "9",
		Args: map[string]any{"path": "inputs/tool-outputs/o1.txt"}, Binding: domain.ReadFileBinding(),
		Policy: api.Policy{Tools: &api.ToolsPolicy{Allowed: []string{}}},
	})
	if err != nil || !out.Out.Success || out.Out.Result != big {
		t.Fatalf("read_file %.80q %v", out.Out.Result, err)
	}
	if len(ws.files) != 1 {
		t.Fatalf("the read was offloaded: %d files", len(ws.files))
	}
}
