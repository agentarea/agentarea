package config

import (
	"fmt"
	"net"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

// Config holds all configuration for the Event Service.
type Config struct {
	DatabaseURL           string
	RedisURL              string
	WorkerID              string
	InboundStream         string
	EnableTelegramPolling bool
	PollInterval          time.Duration
	MaxPollers            int
	Port                  string
}

// Load reads configuration from environment variables with sensible defaults.
func Load() *Config {
	workerID := os.Getenv("AGENTAREA_EVT_WORKER_ID")
	if workerID == "" {
		if hostname, err := os.Hostname(); err == nil {
			workerID = hostname
		} else {
			workerID = "event-service-worker"
		}
	}

	pollInterval := 5 * time.Second
	if v := os.Getenv("AGENTAREA_EVT_POLL_INTERVAL"); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			pollInterval = d
		}
	}

	maxPollers := 200
	if v := os.Getenv("AGENTAREA_EVT_MAX_POLLERS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			maxPollers = n
		}
	}

	inboundStream := os.Getenv("AGENTAREA_EVT_STREAM")
	if inboundStream == "" {
		inboundStream = "agentarea.channel.inbound"
	}

	enableTelegramPolling := false
	if v := os.Getenv("AGENTAREA_EVT_TELEGRAM_ENABLED"); v != "" {
		if parsed, err := strconv.ParseBool(v); err == nil {
			enableTelegramPolling = parsed
		}
	}

	port := os.Getenv("PORT")
	if port == "" {
		port = "8002"
	}

	return &Config{
		DatabaseURL:           databaseURL(),
		RedisURL:              redisURL(),
		WorkerID:              workerID,
		InboundStream:         inboundStream,
		EnableTelegramPolling: enableTelegramPolling,
		PollInterval:          pollInterval,
		MaxPollers:            maxPollers,
		Port:                  port,
	}
}

func databaseURL() string {
	host := os.Getenv("AGENTAREA_DB_HOST")
	port := os.Getenv("AGENTAREA_DB_PORT")
	db := os.Getenv("AGENTAREA_DB_NAME")
	user := os.Getenv("AGENTAREA_DB_USER")
	password := os.Getenv("AGENTAREA_DB_PASSWORD")
	if host == "" || db == "" || user == "" || password == "" {
		return os.Getenv("AGENTAREA_DB_URL")
	}

	sslMode := os.Getenv("AGENTAREA_DB_SSLMODE")
	if sslMode == "" {
		sslMode = "disable"
	}

	return fmt.Sprintf(
		"host=%s port=%s user=%s password=%s dbname=%s sslmode=%s",
		pqConnValue(host),
		pqConnValue(port),
		pqConnValue(user),
		pqConnValue(password),
		pqConnValue(db),
		pqConnValue(sslMode),
	)
}

// redisURL prefers the component variables so a password containing URL-unsafe
// characters is escaped here rather than interpolated raw into a connection
// string. Falls back to the whole URL when no host is given.
func redisURL() string {
	host := os.Getenv("AGENTAREA_REDIS_HOST")
	port := os.Getenv("AGENTAREA_REDIS_PORT")
	password := os.Getenv("AGENTAREA_REDIS_PASSWORD")
	if host == "" {
		return os.Getenv("AGENTAREA_REDIS_URL")
	}

	dsn := url.URL{
		Scheme: "redis",
		Host:   hostPort(host, port),
	}
	if password != "" {
		dsn.User = url.UserPassword("", password)
	}
	return dsn.String()
}

func hostPort(host, port string) string {
	if port == "" {
		return host
	}
	return net.JoinHostPort(host, port)
}

func pqConnValue(value string) string {
	escaped := strings.ReplaceAll(value, `\`, `\\`)
	escaped = strings.ReplaceAll(escaped, `'`, `\'`)
	return "'" + escaped + "'"
}
