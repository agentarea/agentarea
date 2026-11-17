package agents

import (
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
)

func TestA2AAgentURL(t *testing.T) {
	for v, ok := range map[string]bool{
		"http://{agent_id}.a2a.localhost:8000":  true,
		"https://{agent_id}.a2a.example.com/":   true,
		"https://a2a.example.com/{agent_id}":    false,
		"ftp://{agent_id}.a2a.example.com":      false,
		"https://{agent_id}.x/{agent_id}":       false,
		"https://{agent_id}.a2a.example.com/x":  false,
		"https://{agent_id}.a2a.example.com?q":  false,
		"https://{agent_id}.a2a.example.com#f":  false,
		"https://x{agent_id}.a2a.example.com":   false,
		"https://{agent_id}.a2a.example.com:80": true,
	} {
		if err := checkA2AAgentURL(v); (err == nil) != ok {
			t.Errorf("%s: %v", v, err)
		}
	}
	l := config.FromMap(map[string]string{})
	if c := LoadConfig(l); c.A2AAgentURL != "http://{agent_id}.a2a.localhost:8000" || l.Err() != nil {
		t.Error(c, l.Err())
	}
	l = config.FromMap(map[string]string{"AGENTAREA_A2A_AGENT_URL": "https://a2a.example.com"})
	if LoadConfig(l); l.Err() == nil {
		t.Error("expected a failure")
	}
}
