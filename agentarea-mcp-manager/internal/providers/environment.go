package providers

import (
	"fmt"

	"github.com/agentarea/mcp-manager/internal/secrets"
)

func resolveInstanceSpecSecrets(resolver secrets.SecretResolver, instanceID string, source map[string]any) (map[string]any, error) {
	resolved := make(map[string]any, len(source))
	for key, value := range source {
		resolved[key] = value
	}

	environment := make(map[string]any)
	switch values := source["environment"].(type) {
	case map[string]any:
		for key, value := range values {
			environment[key] = value
		}
	case map[string]string:
		for key, value := range values {
			environment[key] = value
		}
	}

	secretNames := make([]string, 0)
	switch values := source["env_vars"].(type) {
	case []any:
		for _, value := range values {
			if name, ok := value.(string); ok && name != "" {
				secretNames = append(secretNames, name)
			}
		}
	case []string:
		secretNames = append(secretNames, values...)
	}

	stringEnvironment := make(map[string]string, len(environment))
	for key, value := range environment {
		stringEnvironment[key] = fmt.Sprint(value)
	}
	if len(secretNames) > 0 {
		if resolver == nil {
			return nil, fmt.Errorf("secret resolver is required for MCP instance %s", instanceID)
		}
		values, err := resolver.ResolveInstanceEnvVars(instanceID, secretNames)
		if err != nil {
			return nil, fmt.Errorf("resolve MCP secret environment: %w", err)
		}
		for _, name := range secretNames {
			value, ok := values[name]
			if !ok {
				return nil, fmt.Errorf("secret resolver omitted requested MCP environment variable %s", name)
			}
			stringEnvironment[name] = value
		}
	}
	if len(stringEnvironment) > 0 {
		resolvedEnvironment := make(map[string]any, len(stringEnvironment))
		for key, value := range stringEnvironment {
			resolvedEnvironment[key] = value
		}
		resolved["environment"] = resolvedEnvironment
	}
	return resolved, nil
}
