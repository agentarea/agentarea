package service

import (
	"reflect"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

func TestBundleToolsAfterReplacesManagedDelegates(t *testing.T) {
	old, fresh, kept := "agent-old", "agent-new", "agent-ui"
	allowed := []domain.MCPPermission{{ToolName: "send"}}
	current := []domain.Tool{
		{Type: domain.ToolMCP, Name: "mcp-1", Settings: &domain.Settings{MCPAllowed: &allowed}},
		{Type: domain.ToolAgent, Name: "writer", Settings: &domain.Settings{AgentID: &old}},
		{Type: domain.ToolAgent, Name: "editor", Settings: &domain.Settings{AgentID: &old}},
		{Type: domain.ToolAgent, Name: "helper", Settings: &domain.Settings{AgentID: &kept}},
	}
	got := bundleToolsAfter(current, catalogapi.BundleAgentUpdate{
		Tools:        []catalogapi.BundleTool{{Type: "mcp", Name: "mcp-1"}, {Type: "agent", Name: "writer", AgentID: &fresh}},
		ManagedTools: []catalogapi.BundleTool{{Type: "mcp", Name: "mcp-1"}, {Type: "agent", Name: "writer"}, {Type: "agent", Name: "editor"}},
	})
	want := []domain.Tool{
		current[0],
		current[3],
		{Type: domain.ToolAgent, Name: "writer", Settings: &domain.Settings{AgentID: &fresh}},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("tools = %+v", got)
	}
}
