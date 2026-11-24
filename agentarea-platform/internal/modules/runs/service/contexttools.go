package service

import (
	"context"
	"errors"
	"fmt"
	"io"
	"sort"
	"strings"
	"unicode/utf8"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

// contextToolset is context_toolset.py: read-only access to the workspace's
// organization library, the artifacts store under its workspace prefix.
const contextToolset = "agentarea/context"

const contextMaxBytes = 5 * 1024 * 1024

type contextTools struct{ store blob.Store }

func (s *Service) contextCaller(in ToolCall) ToolCaller {
	b := in.Binding
	if b.Source != "code" || b.Code == nil || b.Code.Namespace != contextToolset {
		return nil
	}
	return contextTools{store: s.d.Blob}
}

func (t contextTools) Call(ctx context.Context, inv ToolInvocation) (ToolOutput, error) {
	scoped, err := blob.ForWorkspace(t.store, inv.Principal.WorkspaceID)
	if err != nil {
		return ToolOutput{}, err
	}
	var text string
	switch inv.Binding.Code.Method {
	case "list_org_files":
		prefix, _ := inv.Args["prefix"].(string)
		text = listOrgFiles(ctx, scoped, prefix)
	case "read_org_file":
		path, _ := inv.Args["path"].(string)
		text = readOrgFile(ctx, scoped, path)
	default:
		return unknownTool(inv.ToolName), nil
	}
	if strings.HasPrefix(text, "Error") {
		return ToolOutput{Result: text, Error: text, Source: "builtin"}, nil
	}
	return ToolOutput{Success: true, Result: text, Source: "builtin"}, nil
}

func listOrgFiles(ctx context.Context, scoped *blob.Scoped, prefix string) string {
	var paths []string
	for info, err := range scoped.List(ctx, prefix) {
		if err != nil {
			return "Error listing organization files: " + err.Error()
		}
		if sandboxapi.IsReservedPath(info.Key) {
			continue
		}
		paths = append(paths, info.Key)
	}
	if len(paths) == 0 {
		return "No context files found."
	}
	sort.Strings(paths)
	return strings.Join(paths, "\n")
}

func readOrgFile(ctx context.Context, scoped *blob.Scoped, path string) string {
	if path == "" || strings.HasPrefix(path, "/") || strings.Contains(path, "\\") || containsSegment(path, "..") {
		return fmt.Sprintf("Error: path escapes the context store: %q", path)
	}
	if sandboxapi.IsReservedPath(path) {
		return fmt.Sprintf("Error: %s is not in the organization library", path)
	}
	rc, _, err := scoped.Get(ctx, path)
	if errors.Is(err, blob.ErrNotFound) {
		return fmt.Sprintf("Error: organization file %s does not exist", path)
	}
	if err != nil {
		return "Error reading organization file: " + err.Error()
	}
	defer func() { _ = rc.Close() }()
	data, err := io.ReadAll(io.LimitReader(rc, contextMaxBytes+1))
	if err != nil {
		return "Error reading organization file: " + err.Error()
	}
	if len(data) > contextMaxBytes {
		return fmt.Sprintf("Error: organization file %s is larger than %d bytes", path, contextMaxBytes)
	}
	if !utf8.Valid(data) {
		return fmt.Sprintf("Error: organization file %s is not UTF-8 text", path)
	}
	return string(data)
}

func containsSegment(path, seg string) bool {
	for _, s := range strings.Split(path, "/") {
		if s == seg {
			return true
		}
	}
	return false
}
