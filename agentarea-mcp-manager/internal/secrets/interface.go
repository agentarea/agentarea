package secrets

import "context"

// SecretResolver is an interface for resolving secrets from different backends
type SecretResolver interface {
	// ResolveInstanceEnvVars resolves secret env vars by name from the secret store.
	// Used when json_spec.env_vars contains a list of secret names that should be
	// fetched from encrypted_secrets (not from json_spec.environment).
	ResolveInstanceEnvVars(instanceID string, envVarNames []string) (map[string]string, error)

	// Close cleans up any resources used by the resolver
	Close() error
}

// WorkspaceSecretResolver reads one secret of the workspace catalog by name, for a
// consumer that holds a reference to it rather than a copy. Both backends
// NewSecretResolver returns implement it.
type WorkspaceSecretResolver interface {
	ResolveWorkspaceSecret(ctx context.Context, workspaceID, secretName string) (string, error)
}
