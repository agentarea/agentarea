package app

import (
	"context"
	"testing"

	connectionsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	runsservice "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/service"
)

type fakePlatformTools struct{ saw connectionsapi.PlatformCall }

func (f *fakePlatformTools) Call(_ context.Context, c connectionsapi.PlatformCall) (connectionsapi.PlatformResult, error) {
	f.saw = c
	switch c.Method {
	case "nope":
		return connectionsapi.PlatformResult{}, connectionsapi.ErrUnknownPlatformTool
	case "deny":
		return connectionsapi.PlatformResult{Text: "Only a workspace admin may perform this action", IsError: true, StructuredContent: map[string]any{}}, nil
	}
	return connectionsapi.PlatformResult{Text: `{"id":"p1"}`, StructuredContent: map[string]any{"id": "p1"}}, nil
}

func TestPlatformCallerRunsAPlatformToolAsTheRunsAgent(t *testing.T) {
	f := &fakePlatformTools{}
	c := platformCaller{t: f}
	inv := func(method string) runsservice.ToolInvocation {
		return runsservice.ToolInvocation{ToolName: "projects_" + method, Args: map[string]any{"name": "x"},
			Principal: runsservice.Principal{WorkspaceID: "w1", UserID: "u1", AgentID: "a1"},
			Binding:   runsapi.ToolBinding{Source: "code", Code: &runsapi.CodeBinding{Namespace: "agentarea/projects", Method: method}}}
	}
	out, err := c.Call(context.Background(), inv("create"))
	if err != nil || !out.Success || out.Result != `{"id":"p1"}` || out.StructuredContent == nil {
		t.Fatalf("create: %+v %v", out, err)
	}
	if f.saw.AgentID != "a1" || f.saw.WorkspaceID != "w1" || f.saw.Namespace != "agentarea/projects" || string(f.saw.Args) != `{"name":"x"}` {
		t.Fatalf("call %+v", f.saw)
	}
	if out, _ = c.Call(context.Background(), inv("deny")); out.Success || out.Error != "Only a workspace admin may perform this action" || out.StructuredContent != nil {
		t.Fatalf("deny: %+v", out)
	}
	if out, _ = c.Call(context.Background(), inv("nope")); out.Success || out.Error != "Unknown tool: projects_nope" {
		t.Fatalf("unknown: %+v", out)
	}
}
