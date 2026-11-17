package db

import (
	"net"
	"net/url"
	"strconv"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
)

// Config is AGENTAREA_DB_* (config/database.py DatabaseSettings). The
// connection identity has no default: a process that cannot name its
// database does not start. Pool knobs keep Python's defaults.
// AGENTAREA_DB_TENANT_SCOPE is not read: Session carries the scope (D16).
type Config struct {
	Host     string
	Port     int
	Name     string
	User     string
	Password string
	// SSLMode is libpq sslmode; empty leaves the driver default.
	SSLMode          string
	PoolSize         int
	PoolOverflow     int
	PoolTimeout      time.Duration
	PoolRecycle      time.Duration
	Echo             bool
	ReadHost         string
	ReadPort         int
	ReadPoolSize     int
	ReadPoolOverflow int
}

// LoadConfig reads Config. POOL_TIMEOUT and POOL_RECYCLE are whole seconds,
// as Python reads them today.
func LoadConfig(l *config.Loader) Config {
	c := Config{
		Host:             l.RequiredEnv("AGENTAREA_DB_HOST"),
		Port:             l.IntEnv("AGENTAREA_DB_PORT", 5432),
		Name:             l.RequiredEnv("AGENTAREA_DB_NAME"),
		User:             l.RequiredEnv("AGENTAREA_DB_USER"),
		Password:         l.RequiredEnv("AGENTAREA_DB_PASSWORD"),
		SSLMode:          l.OneOfEnv("AGENTAREA_DB_SSLMODE", "", "disable", "allow", "prefer", "require", "verify-ca", "verify-full"),
		PoolSize:         l.IntEnv("AGENTAREA_DB_POOL_SIZE", 20),
		PoolOverflow:     l.IntEnv("AGENTAREA_DB_POOL_OVERFLOW", 30),
		PoolTimeout:      time.Duration(l.IntEnv("AGENTAREA_DB_POOL_TIMEOUT", 30)) * time.Second,
		PoolRecycle:      time.Duration(l.IntEnv("AGENTAREA_DB_POOL_RECYCLE", 3600)) * time.Second,
		Echo:             l.BoolEnv("AGENTAREA_DB_ECHO", false),
		ReadHost:         l.StringEnv("AGENTAREA_DB_READ_HOST", ""),
		ReadPort:         l.IntEnv("AGENTAREA_DB_READ_PORT", 0),
		ReadPoolSize:     l.IntEnv("AGENTAREA_DB_READ_POOL_SIZE", 15),
		ReadPoolOverflow: l.IntEnv("AGENTAREA_DB_READ_POOL_OVERFLOW", 20),
	}
	return c
}

// WriteURL is the primary's connection URL.
func (c Config) WriteURL() string { return c.url(c.Host, c.Port) }

// ReadURL is the replica's URL, the primary's when no replica is configured.
func (c Config) ReadURL() string {
	host, port := c.Host, c.Port
	if c.ReadHost != "" {
		host = c.ReadHost
	}
	if c.ReadPort != 0 {
		port = c.ReadPort
	}
	return c.url(host, port)
}

func (c Config) url(host string, port int) string {
	u := url.URL{
		Scheme: "postgres",
		User:   url.UserPassword(c.User, c.Password),
		Host:   net.JoinHostPort(host, strconv.Itoa(port)),
		Path:   "/" + c.Name,
	}
	if c.SSLMode != "" {
		u.RawQuery = url.Values{"sslmode": {c.SSLMode}}.Encode()
	}
	return u.String()
}
