package config

import (
	"os"
	"strconv"
	"time"
)

// Config holds all configuration for the Event Service.
type Config struct {
	DatabaseURL  string
	RedisURL     string
	WorkerID     string
	PollInterval time.Duration
	MaxPollers   int
}

// Load reads configuration from environment variables with sensible defaults.
func Load() *Config {
	workerID := os.Getenv("WORKER_ID")
	if workerID == "" {
		if hostname, err := os.Hostname(); err == nil {
			workerID = hostname
		} else {
			workerID = "event-service-worker"
		}
	}

	pollInterval := 5 * time.Second
	if v := os.Getenv("POLL_INTERVAL"); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			pollInterval = d
		}
	}

	maxPollers := 200
	if v := os.Getenv("MAX_POLLERS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			maxPollers = n
		}
	}

	return &Config{
		DatabaseURL:  os.Getenv("DATABASE_URL"),
		RedisURL:     os.Getenv("REDIS_URL"),
		WorkerID:     workerID,
		PollInterval: pollInterval,
		MaxPollers:   maxPollers,
	}
}
