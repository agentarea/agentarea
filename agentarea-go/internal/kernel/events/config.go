package events

import (
	"errors"
	"fmt"
	"regexp"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
)

// Config is the broker connection and topic layout every role shares
// (config/broker.py RedisSettings, config/streams.py NAMESPACE and PARTITIONS).
type Config struct {
	// RedisURL has no default, unlike Python's localhost: a process that
	// cannot name its broker does not start (worker main.py _redis_url).
	RedisURL string
	// Namespace is the first segment of every topic, channel and key.
	Namespace string
	// Partitions of the stream-events topic.
	Partitions int
}

// LoadConfig reads Config. AGENTAREA_BROKER must be redis, the only broker
// implemented.
func LoadConfig(l *config.Loader) Config {
	c := Config{
		RedisURL:   l.RequiredEnv("AGENTAREA_REDIS_URL"),
		Namespace:  l.StringEnv("AGENTAREA_EVENT_NAMESPACE", "agentarea"),
		Partitions: l.IntEnv("AGENTAREA_EVENT_PARTITIONS", 16),
	}
	if b := l.OneOfEnv("AGENTAREA_BROKER", "redis", "redis", "kafka"); b != "redis" {
		l.Fail("AGENTAREA_BROKER", fmt.Errorf("%s is not implemented; set redis", b))
	}
	if !regexp.MustCompile(`^[a-z][a-z0-9-]*$`).MatchString(c.Namespace) {
		l.Fail("AGENTAREA_EVENT_NAMESPACE", fmt.Errorf("must match ^[a-z][a-z0-9-]*$, got %q", c.Namespace))
	}
	if c.Partitions < 1 {
		l.Fail("AGENTAREA_EVENT_PARTITIONS", errors.New("must be at least 1"))
	}
	return c
}
