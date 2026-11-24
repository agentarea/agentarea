package service

import "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"

// CodeCatalogue is get_code_tools_metadata over the code toolsets a run
// executes: the sandbox toolsets and the platform toolsets an agent may carry.
type CodeCatalogue struct{}

var _ CodeTools = CodeCatalogue{}

// codePlanes are the platform toolsets' planes (@toolset plane=); a toolset
// with no plane is not offered to agents (agentarea/tools and
// agentarea/workspace_files register no agent toolset).
func codePlanes() map[string]string {
	return map[string]string{
		"agentarea/agents": "build", "agentarea/runs": "operate", "agentarea/task_definitions": "operate",
		"agentarea/skills": "build", "agentarea/projects": "build", "agentarea/clients": "federate",
		"agentarea/members": "govern", "agentarea/policies": "govern", "agentarea/triggers": "build",
		"agentarea/streams": "build", "agentarea/stream_events": "operate", "agentarea/inbox": "operate",
		"agentarea/openapi_connections": "build", "agentarea/mcp_servers": "build", "agentarea/providers": "build",
		"agentarea/models": "build", "agentarea/secrets": "build", "agentarea/audit": "observe",
		"agentarea/network": "observe", "agentarea/workspace_config": "build", "agentarea/messages": "operate",
	}
}

func ref(s string) *string { return &s }

const webNamespace = "agentarea/web"

func sandboxCodeToolsets() []CodeToolset {
	method := func(name, effect, desc string) CodeToolMethod {
		return CodeToolMethod{Name: name, DisplayName: name, Description: desc, Effect: ref(effect)}
	}
	return []CodeToolset{
		{Name: "agentarea/files", DisplayName: "File Operations", Category: "utility", Plane: ref("runtime"), Group: ref("sandbox"),
			Description: "Read, write and list files in this task's working directory, " +
				"the same files the shell sees; read_file also shows images and PDFs. Use the shell for other binary files.",
			RequiresUserConfirmation: true, Methods: []CodeToolMethod{
				method("list_files", "read", "List the files in the working directory."),
				method("read_file", "read", "Read a file from the working directory. Text comes back as text (offset and limit read a range of lines); "+
					"an image (PNG, JPEG, GIF, WebP) is shown to you; a PDF is attached as the pages themselves, at most 20 at a time, "+
					"and pages is required for one over 10 pages."),
				method("save_file", "write", "Write text to a file in the working directory. Text only: "+
					"produce .pdf, .xlsx, images and other binary files with a program in the shell."),
				method("search_files", "read", "Find files in the working directory whose path matches a glob."),
			}},
		{Name: "agentarea/shell", DisplayName: "Shell", Category: "utility", Plane: ref("runtime"), Group: ref("sandbox"),
			Description: "Run bash commands in an isolated sandbox. Each command runs to the end before " +
				"you get its result, and processes it leaves in the background (&, nohup) are " +
				"stopped when it returns, so the shell cannot do anything later on its own.",
			RequiresUserConfirmation: true, Methods: []CodeToolMethod{
				method("bash", "destructive", "Run a bash command and return stdout, stderr, and the exit code."),
			}},
		{Name: "agentarea/context", DisplayName: "Organization Context", Category: "utility", Plane: ref("runtime"),
			Description: "Read the organization library: shared reference files the organization keeps " +
				"for every task (read-only).",
			Methods: []CodeToolMethod{
				method("list_org_files", "read", "List files in the organization library (shared, read-only)."),
				method("read_org_file", "read", "Read a text file from the organization library (shared, read-only)."),
			}},
		{Name: webNamespace, DisplayName: "Web Tools", Category: "information", Plane: ref("runtime"),
			Description:              "Search the web and read web pages into the conversation.",
			RequiresUserConfirmation: true, Methods: []CodeToolMethod{
				method("fetch_webpage", "read", "Read a web page (HTML, text or JSON) and return its text and links. Opens only "+
					"links already seen in this task: in the request, search results or pages read "+
					"before. Binary content (images, PDFs, archives) is refused; download it with "+
					"the shell."),
				method("search_web", "read", "Search the public web; returns titles, links and snippets."),
			}},
		{Name: "agentarea/media", DisplayName: "Media Generation", Category: "media", Plane: ref("runtime"),
			Description: "Generate images and videos with the workspace's image and video models; " +
				"the files are saved to the task workspace.",
			Methods: []CodeToolMethod{
				method("generate_image", "write", "Generate an image from a text prompt and save it to the task workspace."),
				method("generate_video", "write", "Start generating a video from a text prompt; returns a job id for get_video."),
				method("get_video", "write", "Check a video job; once it is done the video is saved to the task workspace."),
			}},
	}
}

// Metadata is every toolset, the sandbox's first, then the platform's in registration order.
func (CodeCatalogue) Metadata() []CodeToolset {
	out := sandboxCodeToolsets()
	planes := codePlanes()
	for _, ts := range domain.ClientPlatformToolsets() {
		plane, ok := planes[ts.Namespace]
		if !ok {
			continue
		}
		methods := make([]CodeToolMethod, len(ts.Methods))
		for i, m := range ts.Methods {
			methods[i] = CodeToolMethod{Name: m.Name, DisplayName: m.DisplayName, Description: m.Description, Effect: ref(m.Effect)}
		}
		out = append(out, CodeToolset{Name: ts.Namespace, Description: ts.Description, DisplayName: ts.DisplayName,
			Category: "platform", Plane: ref(plane), Methods: methods})
	}
	return out
}

// Names are the toolsets' namespaces.
func (c CodeCatalogue) Names() []string {
	md := c.Metadata()
	out := make([]string, len(md))
	for i, ts := range md {
		out[i] = ts.Name
	}
	return out
}
