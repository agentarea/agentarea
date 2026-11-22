package service

import (
	"reflect"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

func TestBundleToolsAfterKeepsDelegateSettingsAndMovesTheAgentID(t *testing.T) {
	old, fresh, kept := "agent-old", "agent-new", "agent-ui"
	confirm, override := true, "Hand finished drafts to the writer"
	allowed := []domain.MCPPermission{{ToolName: "send"}}
	current := []domain.Tool{
		{Type: domain.ToolMCP, Name: "mcp-1", Settings: &domain.Settings{MCPAllowed: &allowed}},
		{Type: domain.ToolAgent, Name: "writer", Settings: &domain.Settings{AgentID: &old, RequiresUserConfirmation: &confirm, DescriptionOverride: &override}},
		{Type: domain.ToolAgent, Name: "editor", Settings: &domain.Settings{AgentID: &old}},
		{Type: domain.ToolAgent, Name: "helper", Settings: &domain.Settings{AgentID: &kept}},
	}
	got := bundleToolsAfter(current, catalogapi.BundleAgentUpdate{
		Tools:        []catalogapi.BundleTool{{Type: "mcp", Name: "mcp-1"}, {Type: "agent", Name: "writer", AgentID: &fresh}},
		ManagedTools: []catalogapi.BundleTool{{Type: "mcp", Name: "mcp-1"}, {Type: "agent", Name: "writer"}, {Type: "agent", Name: "editor"}},
	})
	want := []domain.Tool{
		current[0],
		{Type: domain.ToolAgent, Name: "writer", Settings: &domain.Settings{AgentID: &fresh, RequiresUserConfirmation: &confirm, DescriptionOverride: &override}},
		current[3],
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("tools = %+v", got)
	}
	if *current[1].Settings.AgentID != old {
		t.Fatal("the current tool's settings were written through")
	}
}

// A delegate whose key was renamed is the same agent: its tool takes the new name and keeps its settings.
func TestBundleToolsAfterRenamesADelegateByItsAgentID(t *testing.T) {
	b := "agent-b"
	confirm := true
	current := []domain.Tool{{Type: domain.ToolAgent, Name: "b", Settings: &domain.Settings{AgentID: &b, RequiresUserConfirmation: &confirm}}}
	got := bundleToolsAfter(current, catalogapi.BundleAgentUpdate{
		Tools:        []catalogapi.BundleTool{{Type: "agent", Name: "c", AgentID: &b}},
		ManagedTools: []catalogapi.BundleTool{{Type: "agent", Name: "c", AgentID: &b}},
	})
	want := []domain.Tool{{Type: domain.ToolAgent, Name: "c", Settings: &domain.Settings{AgentID: &b, RequiresUserConfirmation: &confirm}}}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("tools = %+v", got)
	}
}
