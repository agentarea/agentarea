package config

import (
	"errors"
	"time"
)

// Common is what every role reads (layout.md section 7, "Common to every
// role"). The database, broker, Temporal and the rest are loaded by the
// kernel package that owns them.
type Common struct {
	// Env is the deployment environment (AGENTAREA_ENV, default development).
	Env string
	// Edition is oss or enterprise (AGENTAREA_EDITION, default oss): UI
	// badges and the network overlay (features/service.py).
	Edition string
	// LogLevel is DEBUG, INFO, WARNING, ERROR or CRITICAL (AGENTAREA_LOG_LEVEL).
	LogLevel string
	// LogFormat is json or text (AGENTAREA_LOG_FORMAT).
	LogFormat string
	// OTelEnabled installs OpenTelemetry; the rest is the standard OTEL_*
	// variables the SDK reads itself (AGENTAREA_OTEL_ENABLED).
	OTelEnabled bool
	// StartupTimeout bounds starting every component of a role (AGENTAREA_STARTUP_TIMEOUT).
	StartupTimeout time.Duration
	// ShutdownTimeout bounds stopping every component of a role (AGENTAREA_SHUTDOWN_TIMEOUT).
	ShutdownTimeout time.Duration
}

// LoadCommon reads Common. Defaults are today's: Python's AppSettings for
// ENV and EDITION, the Go services' for the rest.
func LoadCommon(l *Loader) Common {
	c := Common{
		Env:             l.StringEnv("AGENTAREA_ENV", "development"),
		Edition:         l.OneOfEnv("AGENTAREA_EDITION", "oss", "oss", "enterprise"),
		LogLevel:        l.OneOfEnv("AGENTAREA_LOG_LEVEL", "INFO", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
		LogFormat:       l.OneOfEnv("AGENTAREA_LOG_FORMAT", "json", "json", "text"),
		OTelEnabled:     l.BoolEnv("AGENTAREA_OTEL_ENABLED", false),
		StartupTimeout:  l.DurationEnv("AGENTAREA_STARTUP_TIMEOUT", 120*time.Second),
		ShutdownTimeout: l.DurationEnv("AGENTAREA_SHUTDOWN_TIMEOUT", 30*time.Second),
	}
	if c.StartupTimeout <= 0 {
		l.Fail("AGENTAREA_STARTUP_TIMEOUT", errors.New("must be positive"))
	}
	if c.ShutdownTimeout <= 0 {
		l.Fail("AGENTAREA_SHUTDOWN_TIMEOUT", errors.New("must be positive"))
	}
	return c
}
