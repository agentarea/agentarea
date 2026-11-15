package agents

import (
	"errors"
	"fmt"
	"net/url"
	"strings"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
)

// A2AAgentIDPlaceholder is the label of AGENTAREA_A2A_AGENT_URL replaced by an agent's id.
const A2AAgentIDPlaceholder = "{agent_id}"

const a2aAgentURLEnv = "AGENTAREA_A2A_AGENT_URL"

// Config is what agents reads from the environment (AppSettings.A2A_AGENT_URL).
type Config struct {
	// A2AAgentURL is where each agent is served over A2A, one host per agent:
	// an http(s) origin whose host starts with "{agent_id}.".
	A2AAgentURL string
}

// LoadConfig reads Config; failures are recorded on l.
func LoadConfig(l *config.Loader) Config {
	v := l.StringEnv(a2aAgentURLEnv, "http://{agent_id}.a2a.localhost:8000")
	if err := checkA2AAgentURL(v); err != nil {
		l.Fail(a2aAgentURLEnv, err)
	}
	return Config{A2AAgentURL: v}
}

// checkA2AAgentURL is AppSettings._check_a2a_agent_url.
func checkA2AAgentURL(v string) error {
	bad := fmt.Errorf("must be an http(s) origin whose host starts with '%s.', e.g. https://%s.a2a.example.com; got %q",
		A2AAgentIDPlaceholder, A2AAgentIDPlaceholder, v)
	if strings.Count(v, A2AAgentIDPlaceholder) != 1 {
		return bad
	}
	u, err := url.Parse(strings.Replace(v, A2AAgentIDPlaceholder, "agent-id-placeholder", 1))
	if err != nil {
		return errors.Join(bad, err)
	}
	host := strings.ToLower(u.Hostname())
	if (u.Scheme != "http" && u.Scheme != "https") || (u.Path != "" && u.Path != "/") ||
		u.RawQuery != "" || u.Fragment != "" || !strings.HasPrefix(host, "agent-id-placeholder.") {
		return bad
	}
	return nil
}
