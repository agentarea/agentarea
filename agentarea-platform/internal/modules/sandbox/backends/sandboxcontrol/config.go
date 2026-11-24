package sandboxcontrol

import (
	"errors"
	"fmt"
	"strconv"
	"time"

	redis "github.com/redis/go-redis/v9"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
)

// Config is the resolved sandbox execution-record configuration. Every process
// that touches execution records builds it once in its composition root and
// injects it, so the API, the embedded runner and the standalone runner cannot
// drift onto different retention windows.
type Config struct {
	RedisPrefix                    string
	ExecutionRecordTTL             time.Duration
	DefaultExecutionTimeoutSeconds int
	MaxExecutionTimeoutSeconds     int
	QueueTimeout                   time.Duration
	CompletionGrace                time.Duration
	RequestStream                  string
	EventStream                    string
}

func (c Config) ExecutionPolicy() ExecutionPolicy {
	return ExecutionPolicy{
		DefaultTimeoutSeconds: c.DefaultExecutionTimeoutSeconds,
		MaxTimeoutSeconds:     c.MaxExecutionTimeoutSeconds,
		QueueTimeout:          c.QueueTimeout,
		CompletionGrace:       c.CompletionGrace,
	}
}

// LoadConfig reads the execution-record configuration; l reports what is
// malformed. The retention window has no default: an assumed TTL silently
// decides how long execution history survives, so a missing or malformed value
// is a startup error.
func LoadConfig(l *config.Loader) Config {
	c := Config{
		RedisPrefix:   l.StringEnv("AGENTAREA_SANDBOX_REDIS_PREFIX", ""),
		RequestStream: l.StringEnv("AGENTAREA_SANDBOX_REQUEST_STREAM", ""),
		EventStream:   l.StringEnv("AGENTAREA_SANDBOX_EVENT_STREAM", ""),
	}
	if value, ok := l.OptionalEnv("AGENTAREA_SANDBOX_RECORD_TTL"); !ok {
		l.Fail("AGENTAREA_SANDBOX_RECORD_TTL", config.ErrMissing)
	} else if ttl, err := time.ParseDuration(value); err != nil {
		l.Fail("AGENTAREA_SANDBOX_RECORD_TTL", fmt.Errorf("must be a duration: %w", err))
	} else if ttl <= 0 {
		l.Fail("AGENTAREA_SANDBOX_RECORD_TTL", fmt.Errorf("must be positive, got %q", value))
	} else {
		c.ExecutionRecordTTL = ttl
	}
	maxTimeout, err := strconv.Atoi(l.StringEnv("AGENTAREA_SANDBOX_MAX_EXEC_SECONDS", ""))
	if err != nil || maxTimeout <= 0 {
		l.Fail("AGENTAREA_SANDBOX_MAX_EXEC_SECONDS", errors.New("must be a positive integer"))
	}
	c.MaxExecutionTimeoutSeconds = maxTimeout
	defaultTimeout, err := strconv.Atoi(l.StringEnv("AGENTAREA_SANDBOX_EXEC_SECONDS", ""))
	if err != nil || defaultTimeout <= 0 || defaultTimeout > maxTimeout {
		l.Fail("AGENTAREA_SANDBOX_EXEC_SECONDS", errors.New("must be a positive integer no greater than AGENTAREA_SANDBOX_MAX_EXEC_SECONDS"))
	}
	c.DefaultExecutionTimeoutSeconds = defaultTimeout
	c.QueueTimeout = positiveDuration(l, "AGENTAREA_SANDBOX_QUEUE_TIMEOUT")
	c.CompletionGrace = positiveDuration(l, "AGENTAREA_SANDBOX_COMPLETION_GRACE")
	return c
}

func positiveDuration(l *config.Loader, name string) time.Duration {
	d, err := time.ParseDuration(l.StringEnv(name, ""))
	if err != nil || d <= 0 {
		l.Fail(name, errors.New("must be a positive duration"))
	}
	return d
}

// NewRedisStoreFromConfig builds the execution-record store over client from
// an already resolved configuration.
func NewRedisStoreFromConfig(client *redis.Client, cfg Config) (*RedisStore, error) {
	return NewRedisStore(
		client,
		cfg.RedisPrefix,
		cfg.ExecutionRecordTTL,
		cfg.ExecutionPolicy(),
		WithEventStreams(cfg.RequestStream, cfg.EventStream, "agentarea.mcp-manager.sandbox-control"),
	)
}
