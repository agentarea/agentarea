package service

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

// sandboxError is SandboxHTTPError: the message becomes the tool's error.
type sandboxError struct{ msg string }

func (e *sandboxError) Error() string { return e.msg }

func sandboxErrf(format string, a ...any) error { return &sandboxError{fmt.Sprintf(format, a...)} }

func toolError(msg string) api.ToolOutcome {
	return api.ToolOutcome{Success: false, Result: "Error: " + msg, Error: msg, Outcome: "error"}
}

// Bash is ShellToolset.bash.
func (r runtime) Bash(ctx context.Context, call api.BashCall) (api.ToolOutcome, error) {
	s := r.s
	if strings.TrimRight(s.d.Manager.URL, "/") == "" {
		return toolError("shell tool is not configured (mcp_manager_url missing)"), nil
	}
	if strings.TrimSpace(call.Command) == "" {
		return toolError("command must be a non-empty string"), nil
	}
	if call.TimeoutSeconds != nil && *call.TimeoutSeconds <= 0 {
		return toolError("timeout_seconds must be positive when supplied"), nil
	}
	command := map[string]any{}
	if call.TimeoutSeconds != nil {
		command["timeout_seconds"] = *call.TimeoutSeconds
	}
	if call.WorkflowID != "" {
		command["workflow_id"] = call.WorkflowID
	}
	if err := r.stageInputs(ctx, call); err != nil {
		if ctx.Err() != nil {
			return api.ToolOutcome{}, ctx.Err()
		}
		s.d.Log.ErrorContext(ctx, "failed to stage task workspace inputs", "error", err)
		return toolError("failed to prepare workspace: " + pyExcText(err)), nil
	}
	command["command_body"] = call.Command
	payload := map[string]any{"command": command}
	for k, v := range map[string]string{"workflow_id": call.WorkflowID, "workspace_id": call.WorkspaceID, "task_id": call.TaskID} {
		if v != "" {
			payload[k] = v
		}
	}
	sg, err := newSigner(s.d.Manager.ControlSecret, call.WorkspaceID, call.TaskID, s.d.Now)
	if err != nil {
		return toolError("shell tool is not configured (" + err.Error() + ")"), nil
	}
	body, err := dumpsSorted(payload)
	if err != nil {
		return api.ToolOutcome{}, err
	}
	u := s.managerURL("/sandbox/executions", nil)
	h, err := sg.headers("execution.create", "", body)
	if err != nil {
		return api.ToolOutcome{}, err
	}
	h.Set("Content-Type", "application/json")
	created, err := s.call(ctx, http.MethodPost, u, h, body, 30*time.Second)
	var result map[string]any
	if err == nil {
		result, err = s.waitForExecution(ctx, created, sg)
	}
	var se *sandboxError
	switch {
	case ctx.Err() != nil:
		return api.ToolOutcome{}, ctx.Err()
	case errors.As(err, &se):
		return toolError(se.msg), nil
	case err != nil:
		s.d.Log.ErrorContext(ctx, "bash request failed", "url", u, "error", err)
		return toolError("failed to reach sandbox: " + err.Error()), nil
	}
	stdout, stderr, err := r.resolveOutputRefs(ctx, call, result)
	if err != nil {
		s.d.Log.ErrorContext(ctx, "sandbox returned invalid output references", "error", err)
		return toolError("sandbox returned invalid output references: " + pyExcText(err)), nil
	}
	return shellOutcome(result, stdout, stderr), nil
}

// pyExcText strips the Go error class prefix the api sentinels add.
func pyExcText(err error) string {
	msg := err.Error()
	for _, sentinel := range []error{api.ErrWorkspaceInvalid, api.ErrWorkspaceConflict, api.ErrWorkspaceQuota} {
		if errors.Is(err, sentinel) {
			msg = strings.TrimPrefix(msg, sentinel.Error()+": ")
		}
	}
	return msg
}

// stageInputs is _stage_inputs: a run in a project gets the project's files
// under inputs/project.
func (r runtime) stageInputs(ctx context.Context, call api.BashCall) error {
	pid := call.ProjectID
	if pid == "" {
		return nil
	}
	if call.WorkspaceID == "" || call.TaskID == "" {
		return errors.New("workspace_id and task_id are required")
	}
	if strings.Contains(pid, "/") || pid == "." || pid == ".." {
		return errors.New("project_id is not a safe object prefix segment")
	}
	_, err := r.s.ws.ImportPrefix(ctx, call.WorkspaceID, call.TaskID, "projects/"+pid, "inputs/project", api.WriteOptions{})
	return err
}

func deadlineReached(v any, now time.Time) (bool, error) {
	str, ok := v.(string)
	if !ok || str == "" {
		return false, sandboxErrf("invalid sandbox status response: missing queue_expires_at")
	}
	t, err := time.Parse(time.RFC3339Nano, str)
	if err != nil {
		if t, err = time.Parse("2006-01-02T15:04:05.999999", str); err != nil {
			return false, sandboxErrf("invalid sandbox status response: malformed queue_expires_at")
		}
	}
	return !now.Before(t), nil
}

func terminalStatus(st string) bool { return st == "completed" || st == "failed" || st == "cancelled" }

// waitForExecution is wait_for_sandbox_execution.
func (s *Service) waitForExecution(ctx context.Context, created managerResponse, sg signer) (map[string]any, error) {
	if created.Status >= 400 {
		return nil, sandboxErrf("sandbox returned HTTP %d: %s", created.Status, created.text())
	}
	record, err := decodeObject(created.Body)
	if err != nil {
		return nil, sandboxErrf("invalid sandbox response: %s", created.text())
	}
	if _, ok := record["id"]; !ok {
		return nil, sandboxErrf("invalid sandbox response: missing execution id")
	}
	id := strOf(record["id"])
	terminal := false
	defer func() {
		st := strOf(record["status"])
		if terminal || (st != "queued" && st != "claimed" && st != "running") {
			return
		}
		if _, err := s.cancelExecution(context.WithoutCancel(ctx), sg, id); err != nil {
			s.d.Log.ErrorContext(ctx, "failed to cancel abandoned sandbox execution", "execution_id", id, "error", err)
		}
	}()
	execURL := s.managerURL("/sandbox/executions/"+id, nil)
	for {
		switch st := strOf(record["status"]); st {
		case "completed":
			terminal = true
			if res, ok := record["result"].(map[string]any); ok {
				return mergeOutputRefs(res, record["output_refs"]), nil
			}
			return record, nil
		case "failed", "cancelled":
			terminal = true
			msg := strOf(record["error"])
			if msg == "" {
				msg = st
			}
			return nil, sandboxErrf("sandbox execution %s: %s", st, msg)
		case "queued":
			due, err := deadlineReached(record["queue_expires_at"], s.d.Now())
			if err != nil {
				return nil, err
			}
			if due {
				if record, err = s.cancelExecution(ctx, sg, id); err != nil {
					return nil, err
				}
				continue
			}
		case "running":
			if v, ok := record["execution_expires_at"]; !ok || v == nil || v == "" {
				return nil, sandboxErrf("invalid sandbox status response: running execution has no deadline")
			}
		}
		h, err := sg.headers("execution.read", id, nil)
		if err != nil {
			return nil, err
		}
		resp, err := s.call(ctx, http.MethodGet, execURL, h, nil, 30*time.Second)
		if err != nil {
			return nil, err
		}
		if resp.Status >= 400 {
			return nil, sandboxErrf("sandbox status returned HTTP %d: %s", resp.Status, resp.text())
		}
		next, err := decodeObject(resp.Body)
		if err != nil {
			return nil, sandboxErrf("invalid sandbox status response: %s", resp.text())
		}
		record = next
		if !terminalStatus(strOf(record["status"])) {
			select {
			case <-ctx.Done():
				return nil, ctx.Err()
			case <-time.After(s.d.PollInterval):
			}
		}
	}
}

func (s *Service) cancelExecution(ctx context.Context, sg signer, id string) (map[string]any, error) {
	u := s.managerURL("/sandbox/executions/"+id, nil)
	h, err := sg.headers("execution.cancel", id, nil)
	if err != nil {
		return nil, err
	}
	resp, err := s.call(ctx, http.MethodDelete, u, h, nil, 30*time.Second)
	if err != nil {
		return nil, err
	}
	if resp.Status == http.StatusConflict {
		if h, err = sg.headers("execution.read", id, nil); err != nil {
			return nil, err
		}
		if resp, err = s.call(ctx, http.MethodGet, u, h, nil, 30*time.Second); err != nil {
			return nil, err
		}
	}
	if resp.Status >= 400 {
		return nil, sandboxErrf("sandbox cancellation returned HTTP %d: %s", resp.Status, resp.text())
	}
	rec, err := decodeObject(resp.Body)
	if err != nil {
		return nil, sandboxErrf("invalid sandbox cancellation response: %s", resp.text())
	}
	return rec, nil
}

// mergeOutputRefs is _merge_committed_output_refs.
func mergeOutputRefs(result map[string]any, outputRefs any) map[string]any {
	list, ok := outputRefs.([]any)
	if !ok {
		return result
	}
	committed := map[string]map[string]any{}
	var order []string
	for _, item := range list {
		m, ok := item.(map[string]any)
		if !ok || strOf(m["relative_path"]) == "" || strOf(m["object_uri"]) == "" {
			continue
		}
		p := strOf(m["relative_path"])
		if _, seen := committed[p]; !seen {
			order = append(order, p)
		}
		committed[p] = m
	}
	if len(committed) == 0 {
		return result
	}
	merged := map[string]any{}
	for k, v := range result {
		merged[k] = v
	}
	values := make([]any, 0, len(order))
	for _, p := range order {
		values = append(values, committed[p])
	}
	if artifacts, ok := result["artifacts"].([]any); ok {
		out := make([]any, 0, len(artifacts))
		used := map[string]bool{}
		for _, a := range artifacts {
			am, ok := a.(map[string]any)
			if !ok {
				out = append(out, a)
				continue
			}
			p := strOf(am["path"])
			if p == "" {
				p = strOf(am["relative_path"])
			}
			ref, has := committed[p]
			if !has {
				out = append(out, am)
				continue
			}
			joined := map[string]any{}
			for k, v := range am {
				joined[k] = v
			}
			for k, v := range ref {
				joined[k] = v
			}
			out = append(out, joined)
			used[p] = true
		}
		for _, p := range order {
			if !used[p] {
				out = append(out, committed[p])
			}
		}
		merged["artifacts"] = out
	} else {
		merged["artifacts"] = values
	}
	merged["output_refs"] = values
	return merged
}

// resolveOutputRefs is _resolve_output_refs: stdout and stderr only by
// reference, read through the task workspace repository.
func (r runtime) resolveOutputRefs(ctx context.Context, call api.BashCall, data map[string]any) (string, string, error) {
	_, hasOut := data["stdout"]
	_, hasErr := data["stderr"]
	if hasOut || hasErr {
		return "", "", errors.New("inline stdout/stderr transport is forbidden")
	}
	var out [2]string
	for i, stream := range []string{"stdout", "stderr"} {
		ref, ok := data[stream+"_ref"].(map[string]any)
		if !ok {
			return "", "", fmt.Errorf("missing %s_ref", stream)
		}
		p := strOf(ref["relative_path"])
		parts := strings.Split(p, "/")
		if !strings.HasPrefix(p, ".agentarea/executions/") || strings.HasPrefix(p, "/") || containsString(parts, "..") || parts[len(parts)-1] != stream+".txt" {
			return "", "", fmt.Errorf("invalid %s_ref path", stream)
		}
		content, err := r.s.ws.GetObjectRef(ctx, call.WorkspaceID, call.TaskID, ref)
		if err != nil {
			return "", "", err
		}
		out[i] = strings.ToValidUTF8(string(content), string(utf8.RuneError))
	}
	return out[0], out[1], nil
}

// shellOutcome is _shell_outcome over the resolved output.
func shellOutcome(data map[string]any, stdout, stderr string) api.ToolOutcome {
	code := int(intOf(data["exit_code"]))
	return api.ToolOutcome{Success: code == 0, Result: formatResult(data["exit_code"], code, stdout, stderr), ExitCode: &code, Outcome: "exit"}
}

func formatResult(raw any, code int, stdout, stderr string) string {
	stdout = strings.TrimRight(stdout, "\n")
	stderr = strings.TrimRight(stderr, "\n")
	shown := "0"
	if raw != nil {
		shown = strOf(raw)
	}
	if code == 0 && stderr == "" && (raw == nil || shown == "0") {
		if stdout == "" {
			return "(command produced no output)"
		}
		return stdout
	}
	parts := []string{"exit_code: " + shown}
	if stdout != "" {
		parts = append(parts, "stdout:\n"+stdout)
	}
	if stderr != "" {
		parts = append(parts, "stderr:\n"+stderr)
	}
	return strings.Join(parts, "\n")
}
