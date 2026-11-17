package service

import (
	"reflect"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
)

func TestConnectionScansOverToolsJSON(t *testing.T) {
	const id = "0b6f5c1e-5d1c-4a8e-9a55-1f0d3c2b7a10"
	harness := "h"
	all := []domain.Agent{
		{ID: "a1", Name: "One", Slug: "one", Status: "active", Tools: []byte(`[{"type":"mcp","name":"` + id + `","settings":{"allowed_tools":[{"tool_name":"x"},"y",{"tool_name":""}]}},{"type":"mcp","name":"gh"}]`)},
		{ID: "a2", Name: "Two", Slug: "two", Status: "archived", Tools: []byte(`[{"type":"mcp","name":"gh"}]`)},
		{ID: "a3", Name: "Three", Slug: "three", Status: "active", HarnessClientID: &harness, Tools: []byte(`[{"type":"mcp","name":"gh"}]`)},
		{ID: "a4", Name: "Four", Slug: "four", Status: "active", Tools: []byte(`{"not":"a list ` + id + `"}`)},
		{ID: "a5", Name: "Five", Slug: "five", Status: "active", Tools: []byte(`[{"type":"builtin","name":"gh"}]`)},
	}
	if got := naming(all, id); !reflect.DeepEqual(got, []string{"a1", "a4"}) {
		t.Fatalf("naming %v", got)
	}
	want := []api.AgentConnectionUse{
		{AgentID: "a1", AgentName: "One", AgentSlug: "one", ServerRef: id, EnabledTools: []string{"x", "y"}},
	}
	if got := mcpUses(all, id, "gh"); !reflect.DeepEqual(got, want) {
		t.Fatalf("consumers %+v", got)
	}
}
