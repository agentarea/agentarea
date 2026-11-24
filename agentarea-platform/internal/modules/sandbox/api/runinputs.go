package api

import (
	"context"
	"errors"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// ErrInputRefused: a run's input cannot be provided (a bad selection, a
// selected file that is gone, an invalid trigger event file); it is final.
var ErrInputRefused = errors.New("run input refused")

// RunInputsRequest names what a run starts with: workspace file paths it
// selected, and the trigger event to write to TriggerEventFileName.
type RunInputsRequest struct {
	TaskID               string
	UserID               string
	Paths                []string
	TriggerEvent         map[string]any
	TriggerEventFileName string
}

// RunInput is one file copied into the task's inputs. Kind is attachment or trigger_event.
type RunInput struct {
	Path        string
	Filename    string
	Kind        string
	SHA256      string
	Size        int64
	ContentType string
}

// RunInputs copies a run's inputs into its task workspace before it starts
// (config.py _prepare_task_files, _prepare_trigger_event_file); a retry
// finds what the first attempt committed.
type RunInputs interface {
	Prepare(ctx context.Context, ws scope.Workspace, req RunInputsRequest) ([]RunInput, error)
}
