package polling

import (
	"errors"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
)

// Config is the pollers' settings, read with the event service's names and defaults; a
// malformed value fails startup instead of falling back to the default.
type Config struct {
	// Interval is how often the set of sources is read again (AGENTAREA_EVENT_POLL_INTERVAL).
	Interval time.Duration
	// MaxPollers caps one replica's pollers (AGENTAREA_EVENT_MAX_POLLERS).
	MaxPollers int
	// WorkerID names this replica's claims (AGENTAREA_EVENT_WORKER_ID, the hostname by default).
	WorkerID string
	// ManagerURL is the MCP manager the MCP Events calls go through (AGENTAREA_MCP_MANAGER_URL).
	ManagerURL string
}

// LoadConfig reads Config; hostname is os.Hostname.
func LoadConfig(l *config.Loader, hostname func() (string, error)) Config {
	c := Config{
		Interval:   l.DurationEnv("AGENTAREA_EVENT_POLL_INTERVAL", 5*time.Second),
		MaxPollers: l.IntEnv("AGENTAREA_EVENT_MAX_POLLERS", 200),
		ManagerURL: strings.TrimRight(l.RequiredEnv("AGENTAREA_MCP_MANAGER_URL"), "/"),
	}
	if c.Interval <= 0 {
		l.Fail("AGENTAREA_EVENT_POLL_INTERVAL", errors.New("must be positive"))
	}
	if c.MaxPollers <= 0 {
		l.Fail("AGENTAREA_EVENT_MAX_POLLERS", errors.New("must be positive"))
	}
	if c.ManagerURL != "" {
		if u, err := url.Parse(c.ManagerURL); err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
			l.Fail("AGENTAREA_MCP_MANAGER_URL", errors.New("must be an http(s) URL"))
		}
	}
	if id, ok := l.OptionalEnv("AGENTAREA_EVENT_WORKER_ID"); ok && id != "" {
		c.WorkerID = id
		return c
	}
	if hostname == nil {
		hostname = os.Hostname
	}
	id, err := hostname()
	if err != nil || id == "" {
		l.Fail("AGENTAREA_EVENT_WORKER_ID", errors.New("unset and the hostname is unknown"))
		return c
	}
	c.WorkerID = id
	return c
}
