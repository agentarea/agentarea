package secrets

import (
	"context"
	"fmt"
	"log/slog"
	"strings"
)

// reservedPrefixes mirrors agentarea_secrets/naming.py RESERVED_PREFIXES: names
// the platform mints for its own owners, never part of a workspace's catalog.
var reservedPrefixes = []string{
	"provider_config_",
	"mcp_instance_",
	"mcp_auth_cred:",
	"channel_cred:",
	"wallet_creds_",
	"openapi:",
	"task-input/",
	"a2a_push_token:",
	"task_webhook:",
}

// RefuseReservedName refuses a reference to a platform-minted secret name.
func RefuseReservedName(secretName string) error {
	for _, prefix := range reservedPrefixes {
		if strings.HasPrefix(secretName, prefix) {
			return fmt.Errorf("secret %s has the platform-reserved prefix %q", secretName, prefix)
		}
	}
	return nil
}

// RefuseReferences refuses a secret reference in a spec layer's environment or
// headers. The platform authorizes a reference only against the instance spec
// that carries it, so any other layer, such as the shared server spec, must
// hold literals only.
func RefuseReferences(layer string, spec map[string]any) error {
	for _, field := range []string{"environment", "headers"} {
		values, _ := spec[field].(map[string]any)
		for name, value := range values {
			switch value.(type) {
			case map[string]any, map[string]string:
				return fmt.Errorf("%s %s.%s is a secret reference; only the instance's own spec may reference a workspace secret", layer, field, name)
			}
		}
	}
	return nil
}

// ResolveValues turns an instance's environment or header values into strings.
// A literal passes through; {"secret_name": "..."} is read from workspaceID's
// catalog on every call, so a rotated secret reaches the next start or request.
// workspaceID must be the instance's own: a reference never reads another
// workspace's catalog.
func ResolveValues(ctx context.Context, resolver WorkspaceSecretResolver, logger *slog.Logger, workspaceID, instanceID string, values map[string]any) (map[string]string, error) {
	resolved := make(map[string]string, len(values))
	for name, value := range values {
		var secretName string
		switch reference := value.(type) {
		case map[string]any:
			secretName, _ = reference["secret_name"].(string)
		case map[string]string:
			secretName = reference["secret_name"]
		default:
			resolved[name] = fmt.Sprint(value)
			continue
		}
		if secretName == "" {
			return nil, fmt.Errorf("%s must be a string or a reference with a secret_name", name)
		}
		if resolver == nil {
			return nil, fmt.Errorf("%s references secret %s, but no secret resolver is configured", name, secretName)
		}
		if err := RefuseReservedName(secretName); err != nil {
			return nil, fmt.Errorf("%s: %w", name, err)
		}
		if workspaceID == "" {
			return nil, fmt.Errorf("%s references secret %s, but instance %s has no workspace", name, secretName, instanceID)
		}
		secret, err := resolver.ResolveWorkspaceSecret(ctx, workspaceID, secretName)
		if err != nil {
			return nil, fmt.Errorf("resolve %s from secret %s: %w", name, secretName, err)
		}
		if secret == "" {
			return nil, fmt.Errorf("%s references secret %s, which is empty", name, secretName)
		}
		logger.Info("Resolved MCP instance secret reference",
			slog.String("instance_id", instanceID),
			slog.String("workspace_id", workspaceID),
			slog.String("name", name),
			slog.String("secret_name", secretName))
		resolved[name] = secret
	}
	return resolved, nil
}
