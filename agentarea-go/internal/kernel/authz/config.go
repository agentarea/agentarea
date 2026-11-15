package authz

import (
	"errors"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
)

// Config is AGENTAREA_AUTHZ_BACKEND (config/access_control.py) and
// AGENTAREA_AUTHZ_FGA_* (config/openfga.py), with Python's defaults.
type Config struct {
	// Backend selects the graph; openfga is the only one. There is no
	// allow-all: a process without a graph does not start.
	Backend string
	URL     string
	// StoreID is required unless Bootstrap finds or creates the store.
	StoreID string
	// ModelID pins checks to one model; empty uses the store's latest.
	// Bootstrap with ApplyModel sets it.
	ModelID string
	Timeout time.Duration
	// Bootstrap finds or creates the store named StoreName when StoreID is empty.
	Bootstrap bool
	// ApplyModel finds the packaged model (or ModelPath's) in the store, or
	// writes it, and pins its id.
	ApplyModel bool
	StoreName  string
	// ModelPath is a deployment's own model, which must extend the packaged one.
	ModelPath string
	// APIToken is sent as a bearer token when the server runs with preshared keys.
	APIToken string
}

// LoadConfig reads Config.
func LoadConfig(l *config.Loader) Config {
	c := Config{
		Backend:    l.OneOfEnv("AGENTAREA_AUTHZ_BACKEND", "openfga", "openfga"),
		URL:        l.StringEnv("AGENTAREA_AUTHZ_FGA_URL", "http://openfga:8080"),
		StoreID:    l.StringEnv("AGENTAREA_AUTHZ_FGA_STORE_ID", ""),
		ModelID:    l.StringEnv("AGENTAREA_AUTHZ_FGA_MODEL_ID", ""),
		Timeout:    l.DurationEnv("AGENTAREA_AUTHZ_FGA_TIMEOUT", 10*time.Second),
		Bootstrap:  l.BoolEnv("AGENTAREA_AUTHZ_FGA_BOOTSTRAP", false),
		ApplyModel: l.BoolEnv("AGENTAREA_AUTHZ_FGA_APPLY_MODEL", false),
		StoreName:  l.StringEnv("AGENTAREA_AUTHZ_FGA_STORE_NAME", "agentarea"),
		ModelPath:  l.StringEnv("AGENTAREA_AUTHZ_FGA_MODEL_PATH", ""),
		APIToken:   l.StringEnv("AGENTAREA_AUTHZ_FGA_API_TOKEN", ""),
	}
	if c.Timeout <= 0 {
		l.Fail("AGENTAREA_AUTHZ_FGA_TIMEOUT", errors.New("must be positive"))
	}
	if c.StoreID == "" && !c.Bootstrap {
		l.Fail("AGENTAREA_AUTHZ_FGA_STORE_ID", errors.New("is required when AGENTAREA_AUTHZ_FGA_BOOTSTRAP is off"))
	}
	return c
}
