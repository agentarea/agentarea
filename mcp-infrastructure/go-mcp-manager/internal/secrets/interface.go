package secrets

// SecretResolver is an interface for resolving secrets from different backends
type SecretResolver interface {
	// ResolveSecrets resolves all environment variables for an MCP instance
	// replacing secret references (secret_ref:xxx) with actual secret values
	ResolveSecrets(instanceID string, envVars map[string]string) (map[string]string, error)

	// Close cleans up any resources used by the resolver
	Close() error
}
