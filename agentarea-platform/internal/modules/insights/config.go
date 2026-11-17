package insights

import (
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/insights/domain"
)

// Config is what insights reads from the environment (config/analytics.py AnalyticsSettings)
// and the edition every analytics event carries.
type Config struct {
	AnalyticsEnabled bool
	Edition          string
	// SignupHookKey is the key Kratos's after-registration hook presents; empty, the hook is off.
	SignupHookKey string
	// OwnDomains are the installation's own sites: a referrer at one or below is no channel.
	OwnDomains []string
}

// LoadConfig reads Config; failures are recorded on l.
func LoadConfig(l *config.Loader) Config {
	c := Config{
		AnalyticsEnabled: l.BoolEnv("AGENTAREA_ANALYTICS_ENABLED", true),
		Edition:          config.LoadCommon(l).Edition,
		SignupHookKey:    l.StringEnv("AGENTAREA_ANALYTICS_SIGNUP_HOOK_KEY", ""),
	}
	own, err := domain.ParseOwnDomains(l.StringEnv("AGENTAREA_ANALYTICS_OWN_DOMAINS", ""))
	if err != nil {
		l.Fail("AGENTAREA_ANALYTICS_OWN_DOMAINS", err)
	}
	c.OwnDomains = own
	return c
}
