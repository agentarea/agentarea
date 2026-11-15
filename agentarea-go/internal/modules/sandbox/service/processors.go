package service

import (
	"context"
	"errors"
	"fmt"
	"math"
	"net/http"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
)

// processorStderrMax is STDERR_MAX_BYTES.
const processorStderrMax = 4096

// processorGrace is how long past the code's own timeout a run may take to queue, start and report.
const processorGrace = 30 * time.Second

// Processors is SandboxCodeRunner over the manager's execution API.
func (s *Service) Processors() api.Processors { return processors{s} }

type processors struct{ s *Service }

func unavailableRun(format string, a ...any) error {
	return fmt.Errorf("%w: %s", api.ErrProcessorUnavailable, fmt.Sprintf(format, a...))
}

// Run is SandboxCodeRunner.run: one signed execution in the session, its
// output read back from the session's files.
func (p processors) Run(ctx context.Context, workspaceID, session, command string, timeout time.Duration, maxOutputBytes int) (api.CodeRun, error) {
	s := p.s
	if strings.TrimRight(s.d.Manager.URL, "/") == "" {
		return api.CodeRun{}, unavailableRun("processors run in the sandbox; set AGENTAREA_MCP_MANAGER_URL")
	}
	seconds := int(math.Ceil(timeout.Seconds()))
	limit := time.Duration(seconds)*time.Second + processorGrace
	runCtx, cancel := context.WithTimeout(ctx, limit)
	defer cancel()
	run, err := p.run(runCtx, workspaceID, session, command, seconds, maxOutputBytes)
	switch {
	case err == nil:
		return run, nil
	case ctx.Err() != nil:
		return api.CodeRun{}, ctx.Err()
	case errors.Is(runCtx.Err(), context.DeadlineExceeded):
		return api.CodeRun{}, unavailableRun("the sandbox did not answer within %.0fs", limit.Seconds())
	}
	s.d.Log.WarnContext(ctx, "processor session could not run", "session", session, "error", err)
	return api.CodeRun{}, unavailableRun("the sandbox could not run it: %v", err)
}

func (p processors) run(ctx context.Context, workspaceID, session, command string, seconds, maxOutputBytes int) (api.CodeRun, error) {
	s := p.s
	sg, err := newSigner(s.d.Manager.ControlSecret, workspaceID, session, s.d.Now)
	if err != nil {
		return api.CodeRun{}, err
	}
	body, err := dumpsSorted(map[string]any{
		"workspace_id": workspaceID,
		"task_id":      session,
		"command": map[string]any{
			"command_body":     command,
			"timeout_seconds":  seconds,
			"stdout_max_bytes": maxOutputBytes,
			"stderr_max_bytes": processorStderrMax,
		},
	})
	if err != nil {
		return api.CodeRun{}, err
	}
	h, err := sg.headers("execution.create", "", body)
	if err != nil {
		return api.CodeRun{}, err
	}
	h.Set("Content-Type", "application/json")
	created, err := s.call(ctx, http.MethodPost, s.managerURL("/sandbox/executions", nil), h, body, 30*time.Second)
	if err != nil {
		return api.CodeRun{}, err
	}
	result, err := s.waitForExecution(ctx, created, sg)
	if err != nil {
		return api.CodeRun{}, err
	}
	code := int(intOf(result["exit_code"]))
	out := api.CodeRun{ExitCode: code, StdoutTruncated: truthy(result["stdout_truncated"])}
	if out.Stdout, err = p.read(ctx, workspaceID, session, result, "stdout"); err != nil {
		return api.CodeRun{}, err
	}
	if code != 0 {
		if out.Stderr, err = p.read(ctx, workspaceID, session, result, "stderr"); err != nil {
			return api.CodeRun{}, err
		}
	}
	return out, nil
}

func (p processors) read(ctx context.Context, workspaceID, session string, result map[string]any, stream string) (string, error) {
	ref, ok := result[stream+"_ref"].(map[string]any)
	if !ok {
		return "", nil
	}
	content, err := p.s.ws.GetObjectRef(ctx, workspaceID, session, ref)
	if err != nil {
		return "", err
	}
	return strings.ToValidUTF8(string(content), string(utf8.RuneError)), nil
}

func truthy(v any) bool {
	switch x := v.(type) {
	case bool:
		return x
	case float64:
		return x != 0
	case string:
		return x != ""
	}
	return v != nil
}
