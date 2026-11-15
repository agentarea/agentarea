package httpx

import (
	"fmt"
	"regexp"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
)

// Config is the edge's part of AppSettings (config/app.py).
type Config struct {
	// MaxBody is the largest request body accepted (AGENTAREA_API_MAX_BODY, default 50 MiB).
	MaxBody int64
	// APIURL is the API's public base URL (AGENTAREA_API_URL); a 401 names
	// its RFC 9728 metadata.
	APIURL string
	CORS   CORSConfig
}

// CORSConfig is Starlette's CORSMiddleware as main.py configures it:
// credentials are never allowed, nothing is exposed, private network
// requests are refused.
type CORSConfig struct {
	// Origins (AGENTAREA_CORS_ORIGINS, default *).
	Origins []string
	// OriginRegex matches further origins whole (AGENTAREA_CORS_ORIGIN_REGEX).
	OriginRegex string
	// Methods (AGENTAREA_CORS_METHODS, default *).
	Methods []string
	// Headers (AGENTAREA_CORS_HEADERS, default *).
	Headers []string
	// MaxAge is the preflight cache in seconds (AGENTAREA_CORS_MAX_AGE, default 3600).
	MaxAge int
}

// LoadConfig reads Config.
func LoadConfig(l *config.Loader) Config {
	c := Config{
		MaxBody: int64(l.IntEnv("AGENTAREA_API_MAX_BODY", 50*1024*1024)),
		APIURL:  l.StringEnv("AGENTAREA_API_URL", "http://localhost:8000"),
		CORS: CORSConfig{
			Origins: l.ListEnv("AGENTAREA_CORS_ORIGINS", []string{"*"}),
			Methods: l.ListEnv("AGENTAREA_CORS_METHODS", []string{"*"}),
			Headers: l.ListEnv("AGENTAREA_CORS_HEADERS", []string{"*"}),
			MaxAge:  l.IntEnv("AGENTAREA_CORS_MAX_AGE", 3600),
		},
	}
	if re, ok := l.OptionalEnv("AGENTAREA_CORS_ORIGIN_REGEX"); ok {
		if _, err := compileFull(re); err != nil {
			l.Fail("AGENTAREA_CORS_ORIGIN_REGEX", err)
		}
		c.CORS.OriginRegex = re
	}
	return c
}

// compileFull compiles re to match a whole string (Python's re.fullmatch).
func compileFull(re string) (*regexp.Regexp, error) {
	compiled, err := regexp.Compile(`^(?:` + re + `)$`)
	if err != nil {
		return nil, fmt.Errorf("not a regular expression: %w", err)
	}
	return compiled, nil
}
