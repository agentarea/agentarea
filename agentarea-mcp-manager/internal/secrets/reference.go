package secrets

import (
	"context"
	"fmt"
	"log/slog"
)

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
		if workspaceID == "" {
			return nil, fmt.Errorf("%s references secret %s, but instance %s has no workspace", name, secretName, instanceID)
		}
		secret, err := resolver.ResolveWorkspaceSecret(ctx, workspaceID, secretName)
		if err != nil {
			return nil, fmt.Errorf("resolve %s from secret %s: %w", name, secretName, err)
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
