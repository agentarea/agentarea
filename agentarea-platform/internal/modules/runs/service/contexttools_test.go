package service

import (
	"context"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

func contextInvocation(method string, args map[string]any) ToolInvocation {
	return ToolInvocation{Principal: Principal{WorkspaceID: "ws-1"}, ToolName: "context_" + method, Args: args,
		Binding: api.ToolBinding{Source: "code", Code: &api.CodeBinding{Namespace: contextToolset, Method: method}}}
}

func TestContextToolsReadOwnWorkspaceOnly(t *testing.T) {
	store := newMemBlob()
	store.m["workspaces/ws-1/brand/voice.md"] = []byte("Calm.")
	store.m["workspaces/ws-1/brand/logo.txt"] = []byte("AA")
	store.m["workspaces/ws-2/secret.md"] = []byte("other tenant")
	store.m["workspaces/ws-1/bin.dat"] = []byte{0xff, 0xfe}
	tools := contextTools{store: store}
	ctx := context.Background()

	out, _ := tools.Call(ctx, contextInvocation("list_org_files", map[string]any{"prefix": "brand/"}))
	if out.Result != "brand/logo.txt\nbrand/voice.md" {
		t.Fatalf("list: %q", out.Result)
	}
	if out, _ := tools.Call(ctx, contextInvocation("read_org_file", map[string]any{"path": "brand/voice.md"})); out.Result != "Calm." || !out.Success {
		t.Fatalf("read: %+v", out)
	}
	for path, want := range map[string]string{
		"../ws-2/secret.md": "escapes", "/brand/voice.md": "escapes", "missing.md": "does not exist", "bin.dat": "not UTF-8",
	} {
		out, _ := tools.Call(ctx, contextInvocation("read_org_file", map[string]any{"path": path}))
		if out.Success || !strings.Contains(out.Result, want) {
			t.Fatalf("%s: %+v", path, out)
		}
	}
	empty := contextTools{store: newMemBlob()}
	if out, _ := empty.Call(ctx, contextInvocation("list_org_files", nil)); out.Result != "No context files found." {
		t.Fatalf("empty: %q", out.Result)
	}
}
