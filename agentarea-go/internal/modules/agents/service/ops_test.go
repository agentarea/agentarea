package service

import (
	"reflect"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
)

func bp(b bool) *bool { return &b }

func TestLiftApprovalsMovesTicksToTargets(t *testing.T) {
	perms := []domain.MCPPermission{{ToolName: "send", RequiresUserConfirmation: bp(true)}, {ToolName: "read", RequiresUserConfirmation: bp(false)}}
	tools := []domain.Tool{
		{Type: domain.ToolCode, Name: "agentarea/shell", Settings: &domain.Settings{RequiresUserConfirmation: bp(true)}},
		{Type: domain.ToolMCP, Name: "srv", Settings: &domain.Settings{MCPAllowed: &perms}},
		{Type: domain.ToolCode, Name: "agentarea/web"},
	}
	targets, stripped := liftApprovals(tools)
	if want := []string{"tool:mcp:srv:send", "tool:shell"}; !reflect.DeepEqual(targets, want) {
		t.Errorf("targets %v, want %v", targets, want)
	}
	if stripped[0].Settings.RequiresUserConfirmation != nil {
		t.Error("the flag is not persisted")
	}
	for _, p := range *stripped[1].Settings.MCPAllowed {
		if p.RequiresUserConfirmation != nil {
			t.Error("per-tool flags are not persisted")
		}
	}
	if tools[0].Settings.RequiresUserConfirmation == nil {
		t.Error("the input is left as it was")
	}
}

func TestApplyTargetsRestoresFlags(t *testing.T) {
	perms := []domain.MCPPermission{{ToolName: "send"}, {ToolName: "read"}}
	got := applyTargets([]domain.Tool{
		{Type: domain.ToolCode, Name: "agentarea/shell"},
		{Type: domain.ToolMCP, Name: "srv", Settings: &domain.Settings{MCPAllowed: &perms}},
	}, []string{"tool:shell", "tool:read"})
	if !*got[0].Settings.RequiresUserConfirmation {
		t.Error("shell ticked")
	}
	p := *got[1].Settings.MCPAllowed
	if *p[0].RequiresUserConfirmation || !*p[1].RequiresUserConfirmation {
		t.Errorf("old bare-name rules still read back: %+v", p)
	}
}

func TestValidHTTPURL(t *testing.T) {
	for u, ok := range map[string]bool{"https://a.test": true, "http://a.test:80/x": true, "ftp://a.test": false, "https://": false, "https://:8": false, "a.test": false} {
		if validHTTPURL(u) != ok {
			t.Errorf("validHTTPURL(%q) != %v", u, ok)
		}
	}
}

func TestAnswerCheckDefaults(t *testing.T) {
	if got := answerCheck([]byte(`{"language":"ru"}`)); got == nil || !got.Enabled || got.Language != "ru" {
		t.Errorf("%+v", got)
	}
	if answerCheck([]byte(`null`)) != nil || answerCheck(nil) != nil {
		t.Error("no policy")
	}
}
