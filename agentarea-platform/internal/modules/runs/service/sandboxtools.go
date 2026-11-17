package service

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"unicode/utf8"

	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

// The shell and file toolsets run in the task's sandbox (shell_toolset,
// file_toolset over SandboxFileStore), so code a run saves is what its
// commands see.
const (
	shellToolset = "agentarea/shell"
	filesToolset = "agentarea/files"
)

// sandboxTools is the code binding of the shell and file toolsets.
type sandboxTools struct{ rt sandboxapi.Runtime }

func (s *Service) sandboxCaller(in ToolCall) ToolCaller {
	b := in.Binding
	if b.Source != "code" || b.Code == nil || s.d.Runtime == nil {
		return nil
	}
	if b.Code.Namespace != shellToolset && b.Code.Namespace != filesToolset {
		return nil
	}
	return sandboxTools{rt: s.d.Runtime}
}

func (t sandboxTools) Call(ctx context.Context, inv ToolInvocation) (ToolOutput, error) {
	ns, method := inv.Binding.Code.Namespace, inv.Binding.Code.Method
	if ns == shellToolset && method == "bash" {
		return t.bash(ctx, inv)
	}
	if ns == filesToolset {
		ws, task := inv.Principal.WorkspaceID, inv.TaskID
		var text string
		var err error
		switch method {
		case "save_file":
			text, err = t.saveFile(ctx, ws, task, inv.Args)
		case "read_file":
			text, err = t.readFile(ctx, ws, task, inv.Args)
		case "list_files":
			text, err = t.listFiles(ctx, ws, task, inv.Args, false)
		case "search_files":
			text, err = t.listFiles(ctx, ws, task, inv.Args, true)
		default:
			return unknownTool(inv.ToolName), nil
		}
		if err != nil {
			return ToolOutput{}, err
		}
		return ToolOutput{Success: true, Result: text, Source: "builtin"}, nil
	}
	return unknownTool(inv.ToolName), nil
}

func unknownTool(name string) ToolOutput {
	return ToolOutput{Result: "MCP tool error: Unknown tool: " + name, Error: "Unknown tool: " + name, Source: "builtin"}
}

func (t sandboxTools) bash(ctx context.Context, inv ToolInvocation) (ToolOutput, error) {
	call := sandboxapi.BashCall{WorkspaceID: inv.Principal.WorkspaceID, TaskID: inv.TaskID, WorkflowID: inv.WorkflowID}
	call.Command, _ = inv.Args["command"].(string)
	if v, ok := inv.Args["timeout_seconds"].(float64); ok {
		n := int(v)
		call.TimeoutSeconds = &n
	}
	if v, ok := inv.RunMetadata["project_id"]; ok && v != nil {
		call.ProjectID = fmt.Sprint(v)
	}
	out, err := t.rt.Bash(ctx, call)
	if err != nil {
		return ToolOutput{}, err
	}
	return ToolOutput{Success: out.Success, Result: out.Result, Error: out.Error, ExitCode: out.ExitCode, Outcome: out.Outcome, Source: "builtin"}, nil
}

func stringArg(args map[string]any, name string) (string, error) {
	v, ok := args[name].(string)
	if !ok {
		return "", fmt.Errorf("missing required argument: %s", governanceapi.PyRepr(name))
	}
	return v, nil
}

func (t sandboxTools) saveFile(ctx context.Context, ws, task string, args map[string]any) (string, error) {
	contents, err := stringArg(args, "contents")
	if err != nil {
		return "", err
	}
	name, err := stringArg(args, "file_name")
	if err != nil {
		return "", err
	}
	overwrite := true
	if v, ok := args["overwrite"].(bool); ok {
		overwrite = v
	}
	if refusal := domain.BinaryFileRefusal(name); refusal != "" {
		return refusal, nil
	}
	if refusal := domain.FilePathRefusal(name); refusal != "" {
		return "Error saving to file: " + refusal, nil
	}
	if !overwrite {
		exists, err := t.rt.FileExists(ctx, ws, task, name)
		if err != nil {
			return "Error saving to file: " + err.Error(), nil
		}
		if exists {
			return "File " + name + " already exists", nil
		}
	}
	if _, err := t.rt.PutFile(ctx, ws, task, name, []byte(contents)); err != nil {
		return "Error saving to file: " + err.Error(), nil
	}
	return name, nil
}

func (t sandboxTools) readFile(ctx context.Context, ws, task string, args map[string]any) (string, error) {
	name, err := stringArg(args, "file_name")
	if err != nil {
		return "", err
	}
	if refusal := domain.FilePathRefusal(name); refusal != "" {
		return "Error reading file: " + refusal, nil
	}
	data, _, err := t.rt.ReadFile(ctx, ws, task, name)
	if errors.Is(err, sandboxapi.ErrFileNotFound) {
		return "Error: File " + name + " does not exist", nil
	}
	if err != nil {
		return "Error reading file: " + err.Error(), nil
	}
	if !utf8.Valid(data) {
		return "Error reading file: 'utf-8' codec can't decode the file", nil
	}
	return string(data), nil
}

func (t sandboxTools) listFiles(ctx context.Context, ws, task string, args map[string]any, search bool) (string, error) {
	pattern := "*"
	if search {
		p, err := stringArg(args, "pattern")
		if err != nil {
			return "", err
		}
		pattern = p
		if isBlank(pattern) {
			return "Error: Pattern cannot be empty", nil
		}
	} else if v, ok := args["pattern"].(string); ok {
		pattern = v
	}
	names, err := t.rt.ListFiles(ctx, ws, task, "")
	if err != nil {
		if search {
			return fmt.Sprintf("Error searching files with pattern '%s': %v", pattern, err), nil
		}
		return "Error listing files: " + err.Error(), nil
	}
	matched := names
	if search || (pattern != "" && pattern != "*") {
		matched = nil
		for _, n := range names {
			if governanceapi.Fnmatch(n, pattern) {
				matched = append(matched, n)
			}
		}
	}
	sorted := append([]string(nil), matched...)
	sort.Strings(sorted)
	if search {
		return domain.FileListing(pattern, "matches_found", true, sorted), nil
	}
	return domain.FileListing(pattern, "files_found", false, sorted), nil
}

func isBlank(s string) bool {
	for _, r := range s {
		if r != ' ' && r != '\t' && r != '\n' && r != '\r' && r != '\v' && r != '\f' {
			return false
		}
	}
	return true
}
