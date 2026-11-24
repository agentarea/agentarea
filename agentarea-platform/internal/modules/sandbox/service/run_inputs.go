package service

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/domain"
)

// RunInputs implements api.RunInputs over the workspace file store and the task workspace.
type RunInputs struct {
	Files     api.Files
	Workspace api.TaskWorkspace
}

var _ api.RunInputs = RunInputs{}

const (
	inputsDir          = "inputs/attachments/"
	maxSelectedFiles   = 100
	triggerEventCT     = "application/json"
	defaultContentType = "application/octet-stream"
)

func refused(msg string) error { return fmt.Errorf("%w: %s", api.ErrInputRefused, msg) }

func inputSHA(data []byte) string {
	h := sha256.Sum256(data)
	return hex.EncodeToString(h[:])
}

// Prepare snapshots the selected files, then writes the trigger event file.
func (r RunInputs) Prepare(ctx context.Context, ws scope.Workspace, req api.RunInputsRequest) ([]api.RunInput, error) {
	out, err := r.selected(ctx, ws, req)
	if err != nil {
		return nil, err
	}
	event, err := r.triggerEvent(ctx, ws, req)
	if err != nil {
		return nil, err
	}
	return append(out, event...), nil
}

type selection struct{ source, taskID, path string }

// selectionOf is the source a selected path names: a workspace file, or a
// file of another task's public workspace.
func selectionOf(raw string) (selection, error) {
	clean, err := domain.NormalizeWorkspacePath(raw)
	if err != nil {
		return selection{}, err
	}
	parts := domain.PosixParts(clean)
	if len(parts) == 0 {
		return selection{}, errors.New("not a file path")
	}
	s := selection{source: clean, path: clean}
	switch {
	case parts[0] == "tasks":
		if len(parts) < 4 || parts[2] != "workspace" {
			return selection{}, errors.New("not a public task workspace path")
		}
		id, err := uuid.Parse(parts[1])
		if err != nil {
			return selection{}, err
		}
		s.taskID = id.String()
		if s.path, err = domain.NormalizeWorkspacePath(strings.Join(parts[3:], "/")); err != nil {
			return selection{}, err
		}
	case parts[0] == "staging" || parts[0] == ".trash" || strings.Contains(clean, "://"):
		return selection{}, errors.New("not a visible workspace file")
	}
	return s, nil
}

func (r RunInputs) selected(ctx context.Context, ws scope.Workspace, req api.RunInputsRequest) ([]api.RunInput, error) {
	if len(req.Paths) == 0 {
		return nil, nil
	}
	if len(req.Paths) > maxSelectedFiles || req.TaskID == "" {
		return nil, refused("Invalid task file selection")
	}
	var sources []selection
	for _, p := range req.Paths {
		s, err := selectionOf(p)
		if err != nil {
			return nil, refused("Invalid task file path")
		}
		dup := false
		for _, have := range sources {
			dup = dup || have == s
		}
		if !dup {
			sources = append(sources, s)
		}
	}
	out := make([]api.RunInput, 0, len(sources))
	for _, s := range sources {
		in, err := r.snapshot(ctx, ws, req, s)
		if err != nil {
			return nil, err
		}
		out = append(out, in)
	}
	return out, nil
}

// snapshot copies one source under a name fixed by the source, so a retry
// reuses the first committed copy even if the source changed or went away.
func (r RunInputs) snapshot(ctx context.Context, ws scope.Workspace, req api.RunInputsRequest, s selection) (api.RunInput, error) {
	sum := sha256.Sum256([]byte(s.source))
	filename := "selected-" + hex.EncodeToString(sum[:])[:16] + "-" + domain.PosixName(s.path)
	target := inputsDir + filename
	data, ct, err := r.Workspace.Get(ctx, ws.ID(), req.TaskID, target)
	if errors.Is(err, api.ErrFileNotFound) {
		data, ct, err = r.source(ctx, ws, s)
		if err != nil {
			return api.RunInput{}, err
		}
		if ct == "" {
			ct = defaultContentType
		}
		_, err = r.Workspace.PutFiles(ctx, ws.ID(), req.TaskID, []api.WorkspaceFile{{Path: target, Data: data, ContentType: ct}},
			api.WriteOptions{Owner: "task-inputs-" + req.TaskID, Actor: userActor(req.UserID)})
		if err != nil {
			return api.RunInput{}, unavailable(err)
		}
	} else if err != nil {
		return api.RunInput{}, err
	}
	if ct == "" {
		ct = defaultContentType
	}
	return api.RunInput{Path: target, Filename: filename, Kind: "attachment", SHA256: inputSHA(data), Size: int64(len(data)), ContentType: ct}, nil
}

// unavailable makes a missing or invalid file a refusal; anything else is an outage.
func unavailable(err error) error {
	if errors.Is(err, api.ErrFileNotFound) || errors.Is(err, api.ErrInvalidPath) || errors.Is(err, api.ErrWorkspaceInvalid) || domain.IsValidation(err) {
		return refused("Selected task file is unavailable")
	}
	return err
}

// source reads the selected file, checked against the digest and size the
// store recorded; one stored without a digest is checked by size alone.
func (r RunInputs) source(ctx context.Context, ws scope.Workspace, s selection) ([]byte, string, error) {
	if s.taskID != "" {
		data, ct, err := r.Workspace.Get(ctx, ws.ID(), s.taskID, s.path)
		return data, ct, unavailable(err)
	}
	head, ok, err := r.Files.Head(ctx, ws, s.path)
	if err != nil {
		return nil, "", unavailable(err)
	}
	if !ok {
		return nil, "", refused("Selected task file is unavailable")
	}
	f, err := r.Files.Get(ctx, ws, s.path)
	if err != nil {
		return nil, "", unavailable(err)
	}
	if int64(len(f.Data)) != head.Size || (head.SHA256 != "" && inputSHA(f.Data) != head.SHA256) {
		return nil, "", refused("Selected task file is unavailable")
	}
	return f.Data, f.ContentType, nil
}

func triggerEventFileName() *regexp.Regexp {
	return regexp.MustCompile(`^trigger-event(?:-\d+)?\.json$`)
}

// eventDataJSON is event_data_json: indent 2, non-ASCII kept. Keys come out sorted.
func eventDataJSON(data map[string]any) ([]byte, error) {
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	enc.SetIndent("", "  ")
	if err := enc.Encode(data); err != nil {
		return nil, err
	}
	return bytes.TrimRight(b.Bytes(), "\n"), nil
}

func (r RunInputs) triggerEvent(ctx context.Context, ws scope.Workspace, req api.RunInputsRequest) ([]api.RunInput, error) {
	name := req.TriggerEventFileName
	if name == "" {
		return nil, nil
	}
	if !triggerEventFileName().MatchString(name) || req.TaskID == "" {
		return nil, refused("Invalid trigger event file")
	}
	if req.TriggerEvent == nil {
		return nil, refused("Trigger event file named without the event data to fill it")
	}
	target := inputsDir + name
	content, _, err := r.Workspace.Get(ctx, ws.ID(), req.TaskID, target)
	if errors.Is(err, api.ErrFileNotFound) {
		if content, err = eventDataJSON(req.TriggerEvent); err != nil {
			return nil, refused("Trigger event data is not JSON: " + err.Error())
		}
		_, err = r.Workspace.PutFiles(ctx, ws.ID(), req.TaskID, []api.WorkspaceFile{{Path: target, Data: content, ContentType: triggerEventCT}},
			api.WriteOptions{Owner: "task-inputs-" + req.TaskID, Actor: userActor(req.UserID)})
	}
	if err != nil {
		return nil, err
	}
	return []api.RunInput{{Path: target, Filename: name, Kind: "trigger_event", SHA256: inputSHA(content), Size: int64(len(content)), ContentType: triggerEventCT}}, nil
}
