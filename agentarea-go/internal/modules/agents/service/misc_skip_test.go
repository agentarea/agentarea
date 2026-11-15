package service

import (
	"context"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
)

type miscFakeMCP struct{ tools []any }

func (f miscFakeMCP) InstanceTools(context.Context, authn.Caller, string) ([]ToolsMCPInstance, error) {
	return []ToolsMCPInstance{{ID: "i", Name: "N", Tools: f.tools}}, nil
}

func TestToolsSkipsAMalformedMCPTool(t *testing.T) {
	w := &warnings{}
	m := NewMisc(New(Deps{Log: w}), MiscDeps{ToolsMCP: miscFakeMCP{tools: []any{
		miscJSON(t, `{"name":5}`), miscJSON(t, `{"name":"ok"}`), miscJSON(t, `"bare"`),
	}}})
	out, err := m.Tools(context.Background(), authn.Caller{}, ToolsQuery{Include: "mcp"})
	if err != nil || len(out) != 1 || w.n != 2 {
		t.Fatalf("out=%v err=%v warnings=%d", out, err, w.n)
	}
	if name, _ := out[0].Get("name"); name != "ok" {
		t.Errorf("%v", out[0])
	}
}
