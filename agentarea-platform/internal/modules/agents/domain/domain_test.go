package domain

import (
	"testing"
)

func TestSlug(t *testing.T) {
	long := ""
	for range 120 {
		long += "a"
	}
	for in, want := range map[string]string{
		"My Agent!": "my-agent", "  --X--  ": "x", "Café Déjà": "cafe-deja", "Привет": "item", "": "item",
		"a_b c": "a-b-c", long: long[:100],
	} {
		if got := Slug(in); got != want {
			t.Errorf("Slug(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestDelegateToolNameAndAddress(t *testing.T) {
	for in, want := range map[string]string{"Web Search": "delegate_to_Web_Search", "9lives": "delegate_to_agent_9lives", "!!": "delegate_to_agent_"} {
		if got := DelegateToolName(in); got != want {
			t.Errorf("DelegateToolName(%q) = %q, want %q", in, got, want)
		}
	}
	if got := AgentAddress(" https://x.test/a/.well-known/agent-card.json "); got != "https://x.test/a" {
		t.Errorf("AgentAddress = %q", got)
	}
}
