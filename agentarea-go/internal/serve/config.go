package serve

import (
	"fmt"
	"net"
	"strconv"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
)

// Config is what the serve role reads.
type Config struct {
	// Addr is the listen address, from HOST and PORT as the Python API read
	// them (apps/api/agentarea_api/cli.py: 0.0.0.0, 8000).
	Addr string
	// Edge is the middleware chain's configuration.
	Edge httpx.Config
	// AppURL is the web app's origin, for links the API hands out
	// (config/app.py APP_URL).
	AppURL string
}

// LoadConfig reads Config; failures are recorded on l.
func LoadConfig(l *config.Loader) Config {
	host := l.StringEnv("HOST", "0.0.0.0")
	port := l.IntEnv("PORT", 8000)
	if port < 0 || port > 65535 {
		l.Fail("PORT", fmt.Errorf("must be a port number, got %d", port))
	}
	return Config{
		Addr:   net.JoinHostPort(host, strconv.Itoa(port)),
		Edge:   httpx.LoadConfig(l),
		AppURL: l.StringEnv("AGENTAREA_APP_URL", "http://localhost:3000"),
	}
}
