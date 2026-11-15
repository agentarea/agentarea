package insights

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
)

// Config is what insights reads from the environment: AGENTAREA_ANALYTICS_ENABLED
// and the edition every analytics event carries.
type Config struct {
	AnalyticsEnabled bool
	Edition          string
}

// LoadConfig reads Config; failures are recorded on l.
func LoadConfig(l *config.Loader) Config {
	return Config{
		AnalyticsEnabled: l.BoolEnv("AGENTAREA_ANALYTICS_ENABLED", true),
		Edition:          config.LoadCommon(l).Edition,
	}
}
