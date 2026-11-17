package service

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

type inputFakeFiles struct {
	api.Files
	objs  map[string]api.File
	heads map[string]api.ObjectHead
}

func (f inputFakeFiles) Head(_ context.Context, _ scope.Workspace, path string) (api.ObjectHead, bool, error) {
	h, ok := f.heads[path]
	return h, ok, nil
}

func (f inputFakeFiles) Get(_ context.Context, _ scope.Workspace, path string) (api.File, error) {
	o, ok := f.objs[path]
	if !ok {
		return api.File{}, api.ErrFileNotFound
	}
	return o, nil
}

type inputFakeWorkspace struct {
	api.TaskWorkspace
	files  map[string][]byte
	types  map[string]string
	owners []string
	puts   int
}

func (w *inputFakeWorkspace) Get(_ context.Context, _, taskID, path string) ([]byte, string, error) {
	d, ok := w.files[taskID+"/"+path]
	if !ok {
		return nil, "", api.ErrFileNotFound
	}
	return d, w.types[taskID+"/"+path], nil
}

func (w *inputFakeWorkspace) PutFiles(_ context.Context, _, taskID string, files []api.WorkspaceFile, opts api.WriteOptions) (api.ManifestRef, error) {
	w.puts++
	w.owners = append(w.owners, opts.Owner)
	for _, f := range files {
		w.files[taskID+"/"+f.Path] = f.Data
		w.types[taskID+"/"+f.Path] = f.ContentType
	}
	return api.ManifestRef{}, nil
}

func inputSetup(t *testing.T) (RunInputs, inputFakeFiles, *inputFakeWorkspace, scope.Workspace) {
	t.Helper()
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	f := inputFakeFiles{objs: map[string]api.File{}, heads: map[string]api.ObjectHead{}}
	w := &inputFakeWorkspace{files: map[string][]byte{}, types: map[string]string{}}
	return RunInputs{Files: f, Workspace: w}, f, w, ws
}

func (f inputFakeFiles) put(path, data, ct, digest string) {
	f.objs[path] = api.File{Data: []byte(data), ContentType: ct}
	f.heads[path] = api.ObjectHead{SHA256: digest, Size: int64(len(data)), ContentType: ct}
}

func TestRunInputsSnapshotSelectedFilesOnce(t *testing.T) {
	ctx := context.Background()
	r, f, w, ws := inputSetup(t)
	task, other := uuid.NewString(), uuid.NewString()
	f.put("docs/report.pdf", "pdf", "application/pdf", inputSHA([]byte("pdf")))
	w.files[other+"/out/data.csv"] = []byte("a,b")
	req := api.RunInputsRequest{TaskID: task, UserID: "u1", Paths: []string{"docs/report.pdf", "docs/report.pdf", "tasks/" + other + "/workspace/out/data.csv"}}

	got, err := r.Prepare(ctx, ws, req)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 || got[0].Kind != "attachment" || got[0].ContentType != "application/pdf" || got[0].Size != 3 ||
		!strings.HasPrefix(got[0].Path, "inputs/attachments/selected-") || !strings.HasSuffix(got[0].Path, "-report.pdf") ||
		got[0].Filename != strings.TrimPrefix(got[0].Path, "inputs/attachments/") || got[1].ContentType != "application/octet-stream" ||
		!strings.HasSuffix(got[1].Path, "-data.csv") || got[0].SHA256 != inputSHA([]byte("pdf")) {
		t.Fatalf("inputs %+v", got)
	}
	if w.puts != 2 || w.owners[0] != "task-inputs-"+task {
		t.Fatalf("puts %d owners %v", w.puts, w.owners)
	}

	f.put("docs/report.pdf", "changed", "application/pdf", inputSHA([]byte("changed")))
	again, err := r.Prepare(ctx, ws, req)
	if err != nil || w.puts != 2 || again[0].SHA256 != got[0].SHA256 {
		t.Fatalf("a retry re-copied: %+v %v puts %d", again, err, w.puts)
	}
}

func TestRunInputsRefuseWhatCannotBeSelected(t *testing.T) {
	ctx := context.Background()
	r, f, _, ws := inputSetup(t)
	f.put("tampered.txt", "abc", "text/plain", inputSHA([]byte("other")))
	for _, paths := range [][]string{
		{"staging/x.txt"}, {".trash/x"}, {"/abs.txt"}, {"../etc/passwd"}, {"tasks/not-a-uuid/workspace/x"},
		{"tasks/" + uuid.NewString() + "/inputs/x"}, {"missing.txt"}, {"tampered.txt"},
		{"tasks/" + uuid.NewString() + "/workspace/missing"}, make([]string, 101),
	} {
		_, err := r.Prepare(ctx, ws, api.RunInputsRequest{TaskID: uuid.NewString(), Paths: paths})
		if !errors.Is(err, api.ErrInputRefused) {
			t.Errorf("%v: got %v", paths, err)
		}
	}
	if _, err := r.Prepare(ctx, ws, api.RunInputsRequest{Paths: []string{"a.txt"}}); !errors.Is(err, api.ErrInputRefused) {
		t.Errorf("no task: %v", err)
	}
}

// Python refused a file stored without a sha256 digest as unavailable
// (config.py:301); it is checked by its size, as downloads are.
func TestRunInputsTakeAFileWithoutADigest(t *testing.T) {
	r, f, _, ws := inputSetup(t)
	f.put("old.txt", "legacy", "text/plain", "")
	got, err := r.Prepare(context.Background(), ws, api.RunInputsRequest{TaskID: uuid.NewString(), Paths: []string{"old.txt"}})
	if err != nil || len(got) != 1 || got[0].Size != 6 {
		t.Fatalf("%+v %v", got, err)
	}
	f.heads["old.txt"] = api.ObjectHead{Size: 99}
	if _, err := r.Prepare(context.Background(), ws, api.RunInputsRequest{TaskID: uuid.NewString(), Paths: []string{"old.txt"}}); !errors.Is(err, api.ErrInputRefused) {
		t.Fatalf("a size mismatch: %v", err)
	}
}

func TestRunInputsWriteTheTriggerEventOnce(t *testing.T) {
	ctx := context.Background()
	r, _, w, ws := inputSetup(t)
	task := uuid.NewString()
	req := api.RunInputsRequest{TaskID: task, TriggerEventFileName: "trigger-event-3.json", TriggerEvent: map[string]any{"b": "<é>", "a": 1}}
	got, err := r.Prepare(ctx, ws, req)
	if err != nil {
		t.Fatal(err)
	}
	want := "{\n  \"a\": 1,\n  \"b\": \"<é>\"\n}"
	if len(got) != 1 || got[0].Path != "inputs/attachments/trigger-event-3.json" || got[0].Kind != "trigger_event" ||
		string(w.files[task+"/"+got[0].Path]) != want || got[0].ContentType != "application/json" {
		t.Fatalf("%+v %q", got, w.files[task+"/inputs/attachments/trigger-event-3.json"])
	}
	req.TriggerEvent = map[string]any{"changed": true}
	if again, err := r.Prepare(ctx, ws, req); err != nil || w.puts != 1 || again[0].SHA256 != got[0].SHA256 {
		t.Fatalf("a retry rewrote the event: %+v %v", again, err)
	}
	for _, bad := range []api.RunInputsRequest{
		{TaskID: task, TriggerEventFileName: "event.json", TriggerEvent: map[string]any{}},
		{TaskID: task, TriggerEventFileName: "trigger-event.json"},
		{TriggerEventFileName: "trigger-event.json", TriggerEvent: map[string]any{}},
	} {
		if _, err := r.Prepare(ctx, ws, bad); !errors.Is(err, api.ErrInputRefused) {
			t.Errorf("%+v: %v", bad, err)
		}
	}
	if got, err := r.Prepare(ctx, ws, api.RunInputsRequest{TaskID: task}); err != nil || len(got) != 0 {
		t.Fatalf("no inputs: %+v %v", got, err)
	}
}
