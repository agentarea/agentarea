package service

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/api/contract"
)

// CodeMethod is one method of a code toolset as a run offers it.
type CodeMethod struct {
	Method      string
	Description string
	Parameters  map[string]any
}

// CodeToolset is a code toolset (agentarea/<name>) and its methods.
type CodeToolset struct {
	Namespace   string
	Description string
	Methods     []CodeMethod
}

// ShortName is the namespace's last segment (Toolset.name).
func (t CodeToolset) ShortName() string {
	return t.Namespace[strings.LastIndex(t.Namespace, "/")+1:]
}

// ToolName is the model-facing name of a method: the toolset's name when it
// has one method, else <toolset>_<method> (Toolset.get_tool_definitions).
func (t CodeToolset) ToolName(method string) string {
	if len(t.Methods) == 1 {
		return t.ShortName()
	}
	return t.ShortName() + "_" + method
}

func obj(props map[string]any, required ...string) map[string]any {
	s := map[string]any{"type": "object", "properties": props}
	if len(required) > 0 {
		s["required"] = required
	}
	return s
}

func str(desc string) map[string]any { return map[string]any{"type": "string", "description": desc} }

// sandboxToolsets are the code toolsets runs executes in the task's sandbox
// (file_toolset.py, shell_toolset.py).
func sandboxToolsets() []CodeToolset {
	return []CodeToolset{
		{Namespace: "agentarea/files", Description: "Read, write and list files in this task's working directory, " +
			"the same files the shell sees; read_file also shows images and PDFs. Use the shell for other binary files.", Methods: []CodeMethod{
			{Method: "save_file", Description: "Write text to a file in the working directory. Text only: " +
				"produce .pdf, .xlsx, images and other binary files with a program in the shell.",
				Parameters: obj(map[string]any{
					"contents":  str("The full text to write."),
					"file_name": str("Path relative to the working directory, e.g. outputs/summary.md."),
					"overwrite": map[string]any{"type": "boolean", "default": true, "description": "Replace an existing file; false refuses to."},
				}, "contents", "file_name")},
			{Method: "read_file", Description: "Read a file from the working directory. Text comes back as text (offset and limit " +
				"read a range of lines); an image (PNG, JPEG, GIF, WebP) is shown to you; a PDF is attached as the pages themselves, " +
				"at most 20 at a time, and pages is required for one over 10 pages.",
				Parameters: obj(map[string]any{
					"file_name": str("Path relative to the working directory, e.g. inputs/brief.txt."),
					"pages":     str(`PDF pages to read, one page or a range, e.g. "3" or "1-5"; at most 20.`),
					"offset":    map[string]any{"type": "integer", "description": "Text: the line to start from, 1-based."},
					"limit":     map[string]any{"type": "integer", "description": "Text: how many lines to read."},
				}, "file_name")},
			{Method: "list_files", Description: "List the files in the working directory.",
				Parameters: obj(map[string]any{"pattern": map[string]any{"type": "string", "default": "*",
					"description": "Glob over paths relative to the working directory, e.g. *.csv; * lists all."}})},
			{Method: "search_files", Description: "Find files in the working directory whose path matches a glob.",
				Parameters: obj(map[string]any{"pattern": str("Glob over paths relative to the working directory, e.g. outputs/*.md.")}, "pattern")},
		}},
		{Namespace: "agentarea/shell", Description: "Run bash commands in an isolated sandbox. Each command runs to the end before " +
			"you get its result, and processes it leaves in the background (&, nohup) are stopped when it returns, " +
			"so the shell cannot do anything later on its own.", Methods: []CodeMethod{
			{Method: "bash", Description: "Run a bash command and return stdout, stderr, and the exit code.",
				Parameters: obj(map[string]any{
					"command": str("The bash command to run. It starts in the task's working directory; use paths relative to it, " +
						"such as outputs/report.md. Chain steps with && or put them in a script."),
					"timeout_seconds": map[string]any{"type": []any{"integer", "null"}, "default": nil,
						"description": "Seconds the command may run before it is stopped. Omit for the default; asking for more " +
							"than the sandbox allows returns an error naming the maximum."},
				}, "command")},
		}},
	}
}

// runtimeToolsets are the code toolsets runs executes itself, outside the
// sandbox (context_toolset.py, web_toolset.py, media_toolset.py).
func runtimeToolsets() []CodeToolset {
	return []CodeToolset{
		{Namespace: "agentarea/context", Description: "Read the organization library: shared reference files the organization keeps " +
			"for every task (read-only).", Methods: []CodeMethod{
			{Method: "list_org_files", Description: "List files in the organization library (shared, read-only). These are the " +
				"organization's durable shared files, distinct from your own task files (the files tool).",
				Parameters: obj(map[string]any{"prefix": map[string]any{"type": "string", "default": "",
					"description": "Only paths starting with this; empty lists all."}})},
			{Method: "read_org_file", Description: "Read a text file from the organization library (shared, read-only).",
				Parameters: obj(map[string]any{"path": str("Path as list_org_files returns it.")}, "path")},
		}},
		{Namespace: "agentarea/web", Description: "Search the web and read web pages into the conversation.", Methods: []CodeMethod{
			{Method: "fetch_webpage", Description: "Read a web page (HTML, text or JSON) and return its text and links. Opens only " +
				"links already seen in this task: in the request, search results or pages read before. Binary content " +
				"(images, PDFs, archives) is refused; download it with the shell.",
				Parameters: obj(map[string]any{
					"url":             str("Full http(s) URL of the page."),
					"timeout_seconds": map[string]any{"type": "number", "default": 15.0, "description": "Seconds to wait for the page."},
				}, "url")},
			{Method: "search_web", Description: "Search the public web; returns titles, links and snippets.",
				Parameters: obj(map[string]any{
					"query":       str("What to search for, as you would type it."),
					"max_results": map[string]any{"type": "integer", "default": 8, "description": "How many results, 1 to 20."},
				}, "query")},
		}},
		{Namespace: "agentarea/media", Description: "Generate images and videos with the workspace's image and video models; " +
			"the files are saved to the task workspace.", Methods: []CodeMethod{
			{Method: "generate_image", Description: "Generate an image from a text prompt and save it to the task workspace.",
				Parameters: obj(map[string]any{
					"prompt": str("What the image shows."),
					"size": map[string]any{"type": []any{"string", "null"}, "default": nil,
						"description": "Optional WIDTHxHEIGHT hint such as 1024x1536."},
				}, "prompt")},
			{Method: "generate_video", Description: "Start generating a video from a text prompt; returns a job id for get_video. " +
				"Generation takes minutes: poll get_video with the job id.",
				Parameters: obj(map[string]any{
					"prompt":       str("What the video shows."),
					"duration":     map[string]any{"type": []any{"integer", "null"}, "default": nil, "description": "Length in seconds."},
					"resolution":   map[string]any{"type": []any{"string", "null"}, "default": nil, "description": "Resolution such as 720p."},
					"aspect_ratio": map[string]any{"type": []any{"string", "null"}, "default": nil, "description": "Aspect ratio such as 16:9."},
				}, "prompt")},
			{Method: "get_video", Description: "Check a video job; once it is done the video is saved to the task workspace.",
				Parameters: obj(map[string]any{"job_id": str("The job id generate_video returned.")}, "job_id")},
		}},
	}
}

// platformToolsets are the platform toolsets as the workspace-pinned MCP
// mount lists them (mcp-tools.json), one method per tool.
func platformToolsets() ([]CodeToolset, error) {
	tools, err := contract.LoadMCPTools()
	if err != nil {
		return nil, err
	}
	byName := map[string]*CodeToolset{}
	var order []string
	for _, t := range tools.PlatformPinned.Tools {
		ts, ok := byName[t.Toolset]
		if !ok {
			ts = &CodeToolset{Namespace: "agentarea/" + t.Toolset}
			byName[t.Toolset] = ts
			order = append(order, t.Toolset)
		}
		var params map[string]any
		if len(t.InputSchema) > 0 {
			if err := json.Unmarshal(t.InputSchema, &params); err != nil {
				return nil, fmt.Errorf("mcp-tools.json %s: %w", t.Name, err)
			}
		}
		if params == nil {
			params = obj(map[string]any{})
		}
		ts.Methods = append(ts.Methods, CodeMethod{Method: strings.TrimPrefix(t.Name, t.Toolset+"_"), Description: t.Description, Parameters: params})
	}
	out := make([]CodeToolset, 0, len(order))
	for _, name := range order {
		ts := byName[name]
		sort.SliceStable(ts.Methods, func(i, j int) bool { return ts.Methods[i].Method < ts.Methods[j].Method })
		out = append(out, *ts)
	}
	return out, nil
}

// CodeToolsets are the code toolsets a run may name, by namespace.
func CodeToolsets() (map[string]CodeToolset, error) {
	platform, err := platformToolsets()
	if err != nil {
		return nil, err
	}
	out := map[string]CodeToolset{}
	for _, t := range append(append(platform, sandboxToolsets()...), runtimeToolsets()...) {
		out[t.Namespace] = t
	}
	return out, nil
}
