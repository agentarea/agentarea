package blob

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
)

// Config is AGENTAREA_S3_* (config/aws.py AWSSettings).
type Config struct {
	// Endpoint is the internal S3 endpoint; empty means AWS.
	Endpoint string
	// PublicEndpoint is the host presigned URLs are signed against, reachable
	// by browsers and sandboxes; empty means Endpoint.
	PublicEndpoint string
	Region         string
	// Bucket holds harness files and event archives; ArtifactsBucket holds the
	// workspace file store.
	Bucket          string
	ArtifactsBucket string
	AccessKey       string
	SecretKey       string
}

// LoadConfig reads Config. Defaults are Python's (region us-east-1, buckets
// ai-agents-bucket and artifacts) except for the credentials: Python's
// minioadmin/minioadmin suit a local RustFS only and
// require_s3_credentials() already refuses them wherever a write must land,
// so a process that cannot name its credentials does not start.
func LoadConfig(l *config.Loader) Config {
	endpoint, _ := l.OptionalEnv("AGENTAREA_S3_ENDPOINT")
	public, _ := l.OptionalEnv("AGENTAREA_S3_PUBLIC_ENDPOINT")
	return Config{
		Endpoint:        endpoint,
		PublicEndpoint:  public,
		Region:          l.StringEnv("AGENTAREA_S3_REGION", "us-east-1"),
		Bucket:          l.StringEnv("AGENTAREA_S3_BUCKET", "ai-agents-bucket"),
		ArtifactsBucket: l.StringEnv("AGENTAREA_S3_ARTIFACTS_BUCKET", "artifacts"),
		AccessKey:       l.RequiredEnv("AGENTAREA_S3_ACCESS_KEY"),
		SecretKey:       l.RequiredEnv("AGENTAREA_S3_SECRET_KEY"),
	}
}

// Signing is the endpoint presigned URLs use.
func (c Config) Signing() string {
	if c.PublicEndpoint != "" {
		return c.PublicEndpoint
	}
	return c.Endpoint
}
