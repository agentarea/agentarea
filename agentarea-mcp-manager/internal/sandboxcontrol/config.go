package sandboxcontrol

import (
	"fmt"
	"os"
	"strconv"
	"time"
)

// Config is the resolved sandbox execution-record configuration. Every process
// that touches execution records builds it once in its composition root and
// injects it, so the API, the embedded runner and the standalone runner cannot
// drift onto different retention windows.
type Config struct {
	RedisURL                       string
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

// LoadConfigFromEnv resolves execution-record configuration. The retention
// window has no default: an assumed TTL silently decides how long execution
// history survives, so a missing or malformed value is a startup error.
func LoadConfigFromEnv(redisURL string) (Config, error) {
	value := os.Getenv("AGENTAREA_SBX_RECORD_TTL")
	if value == "" {
		return Config{}, fmt.Errorf("AGENTAREA_SBX_RECORD_TTL is required")
	}
	ttl, err := time.ParseDuration(value)
	if err != nil {
		return Config{}, fmt.Errorf("AGENTAREA_SBX_RECORD_TTL must be a duration: %w", err)
	}
	if ttl <= 0 {
		return Config{}, fmt.Errorf("AGENTAREA_SBX_RECORD_TTL must be positive, got %q", value)
	}
	if redisURL == "" {
		return Config{}, fmt.Errorf("sandbox control plane requires a Redis URL")
	}
	maxTimeoutRaw := os.Getenv("AGENTAREA_SBX_MAX_EXEC_SECONDS")
	maxTimeout, err := strconv.Atoi(maxTimeoutRaw)
	if maxTimeoutRaw == "" || err != nil || maxTimeout <= 0 {
		return Config{}, fmt.Errorf("AGENTAREA_SBX_MAX_EXEC_SECONDS must be a positive integer")
	}
	defaultTimeoutRaw := os.Getenv("AGENTAREA_SBX_EXEC_SECONDS")
	defaultTimeout, err := strconv.Atoi(defaultTimeoutRaw)
	if defaultTimeoutRaw == "" || err != nil || defaultTimeout <= 0 || defaultTimeout > maxTimeout {
		return Config{}, fmt.Errorf("AGENTAREA_SBX_EXEC_SECONDS must be a positive integer no greater than AGENTAREA_SBX_MAX_EXEC_SECONDS")
	}
	queueTimeoutRaw := os.Getenv("AGENTAREA_SBX_QUEUE_TIMEOUT")
	queueTimeout, err := time.ParseDuration(queueTimeoutRaw)
	if queueTimeoutRaw == "" || err != nil || queueTimeout <= 0 {
		return Config{}, fmt.Errorf("AGENTAREA_SBX_QUEUE_TIMEOUT must be a positive duration")
	}
	completionGraceRaw := os.Getenv("AGENTAREA_SBX_COMPLETION_GRACE")
	completionGrace, err := time.ParseDuration(completionGraceRaw)
	if completionGraceRaw == "" || err != nil || completionGrace <= 0 {
		return Config{}, fmt.Errorf("AGENTAREA_SBX_COMPLETION_GRACE must be a positive duration")
	}
	return Config{
		RedisURL:                       redisURL,
		RedisPrefix:                    os.Getenv("AGENTAREA_SBX_REDIS_PREFIX"),
		ExecutionRecordTTL:             ttl,
		DefaultExecutionTimeoutSeconds: defaultTimeout,
		MaxExecutionTimeoutSeconds:     maxTimeout,
		QueueTimeout:                   queueTimeout,
		CompletionGrace:                completionGrace,
		RequestStream:                  os.Getenv("AGENTAREA_SBX_REQUEST_STREAM"),
		EventStream:                    os.Getenv("AGENTAREA_SBX_EVENT_STREAM"),
	}, nil
}

// NewRedisStoreFromConfig builds the execution-record store from an already
// resolved configuration.
func NewRedisStoreFromConfig(cfg Config) (*RedisStore, error) {
	return NewRedisStore(
		cfg.RedisURL,
		cfg.RedisPrefix,
		cfg.ExecutionRecordTTL,
		cfg.ExecutionPolicy(),
		WithEventStreams(cfg.RequestStream, cfg.EventStream, "agentarea.mcp-manager.sandbox-control"),
	)
}
