package service

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"sort"
	"strings"
	"unicode/utf8"

	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

// The shell and file toolsets run in the task's sandbox (shell_toolset,
// file_toolset over SandboxFileStore), so code a run saves is what its
// commands see; the built-in read_file reads a task input from the task
// workspace without one.
const (
	shellToolset = "agentarea/shell"
	filesToolset = domain.FilesToolset
)

// sandboxTools is the code binding of the shell and file toolsets.
type sandboxTools struct {
	rt sandboxapi.Runtime
	ws sandboxapi.TaskWorkspace
}

func (s *Service) sandboxCaller(in ToolCall) ToolCaller {
	b := in.Binding
	if b.Source != "code" || b.Code == nil || s.d.Runtime == nil {
		return nil
	}
	if b.Code.Namespace != shellToolset && b.Code.Namespace != filesToolset {
		return nil
	}
	return sandboxTools{rt: s.d.Runtime, ws: s.d.Workspace}
}

// WorkspaceTaskKey names, in a run's metadata, the task whose files the run works on: a
// subtask works on its parent's.
const WorkspaceTaskKey = "workspace_task_id"

// filesTask is the task whose sandbox and files a call works on.
func filesTask(inv ToolInvocation) string {
	if t, _ := inv.RunMetadata[WorkspaceTaskKey].(string); t != "" {
		return t
	}
	return inv.TaskID
}

func (t sandboxTools) Call(ctx context.Context, inv ToolInvocation) (ToolOutput, error) {
	ns, method := inv.Binding.Code.Namespace, inv.Binding.Code.Method
	if ns == shellToolset && method == "bash" {
		return t.bash(ctx, inv)
	}
	if ns == filesToolset {
		ws, task := inv.Principal.WorkspaceID, filesTask(inv)
		if method == "read_file" {
			return t.readFile(ctx, ws, task, inv.Args)
		}
		var text string
		var err error
		switch method {
		case "save_file":
			text, err = t.saveFile(ctx, ws, task, inv.Args)
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
	call := sandboxapi.BashCall{WorkspaceID: inv.Principal.WorkspaceID, TaskID: filesTask(inv), WorkflowID: inv.WorkflowID}
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

// readFile is read_file: a text file as text (offset and limit by line, then
// grep, head or tail, capped), an image as the image itself, a PDF's pages as
// a PDF file.
func (t sandboxTools) readFile(ctx context.Context, ws, task string, args map[string]any) (ToolOutput, error) {
	text := func(s string) (ToolOutput, error) {
		return ToolOutput{Success: true, Result: s, Source: "builtin"}, nil
	}
	name, err := stringArg(args, "path")
	if err != nil {
		return ToolOutput{}, err
	}
	pages, _ := args["pages"].(string)
	grep, _ := args["grep"].(string)
	offset, limit := intArg(args, "offset"), intArg(args, "limit")
	head, tail := intArg(args, "head"), intArg(args, "tail")
	if refusal := domain.FilePathRefusal(name); refusal != "" {
		return text("Error reading file: " + refusal)
	}
	data, err := t.read(ctx, ws, task, name)
	if errors.Is(err, sandboxapi.ErrFileNotFound) {
		return text("Error: File " + name + " does not exist")
	}
	if err != nil {
		return text("Error reading file: " + err.Error())
	}
	failed := func(why string) (ToolOutput, error) { return text("Error reading file: " + name + ": " + why) }
	if http.DetectContentType(data) == pdfMimeType {
		out, why := readPDF(ctx, name, data, pages)
		if why != "" {
			return failed(why)
		}
		return out, nil
	}
	if pages != "" {
		return failed("pages is for PDF files")
	}
	info, isImage, err := inspectImage(data)
	if err != nil {
		return failed(err.Error())
	}
	if isImage {
		return ToolOutput{Success: true, Result: imageReadNote(name, info, len(data)), Source: "builtin",
			Images: []ToolImage{{Data: data, MimeType: info.MimeType}}}, nil
	}
	if !utf8.Valid(data) {
		return text("Error reading file: 'utf-8' codec can't decode the file")
	}
	content := string(data)
	if offset != 0 || limit != 0 {
		var why string
		if content, why = readLines(content, offset, limit); why != "" {
			return failed(why)
		}
	}
	return text(domain.FilterOutput(content, grep, &head, &tail))
}

// read is a task input from the task workspace, any other file from the sandbox.
func (t sandboxTools) read(ctx context.Context, ws, task, name string) ([]byte, error) {
	if !strings.HasPrefix(name, domain.TaskInputsPrefix) {
		data, _, err := t.rt.ReadFile(ctx, ws, task, name)
		return data, err
	}
	if t.ws == nil {
		return nil, errors.New("task input files cannot be read: this deployment has no task workspace")
	}
	data, _, err := t.ws.Get(ctx, ws, task, name)
	return data, err
}

func intArg(args map[string]any, name string) int {
	if v, ok := args[name].(float64); ok && v > 0 {
		return int(v)
	}
	return 0
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
		re := governanceapi.CompileFnmatch(pattern)
		for _, n := range names {
			if re.MatchString(n) {
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
