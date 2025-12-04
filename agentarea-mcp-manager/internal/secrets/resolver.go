package secrets

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"strings"

	infisical "github.com/infisical/go-sdk"
)

// InfisicalConfig represents the bootstrap configuration structure
type InfisicalConfig struct {
	Message      string `json:"message"`
	User         User   `json:"user"`
	Organization Org    `json:"organization"`
	Identity     Ident  `json:"identity"`
}

type User struct {
	Username   string `json:"username"`
	FirstName  string `json:"firstName"`
	LastName   string `json:"lastName"`
	Email      string `json:"email"`
	ID         string `json:"id"`
	SuperAdmin bool   `json:"superAdmin"`
}

type Org struct {
	ID   string `json:"id"`
	Name string `json:"name"`
	Slug string `json:"slug"`
}

type Ident struct {
	ID          string      `json:"id"`
	Name        string      `json:"name"`
	Credentials Credentials `json:"credentials"`
}

type Credentials struct {
	Token string `json:"token"`
}

// InfisicalSecretResolver handles secure secret resolution using Infisical SDK
type InfisicalSecretResolver struct {
	client      infisical.InfisicalClientInterface
	logger      *slog.Logger
	projectID   string
	environment string
}

// NewSecretResolver creates the appropriate secret resolver based on SECRET_MANAGER_TYPE
func NewSecretResolver(logger *slog.Logger) (SecretResolver, error) {
	secretManagerType := os.Getenv("SECRET_MANAGER_TYPE")
	if secretManagerType == "" {
		secretManagerType = "database" // Default to database
	}

	logger.Info("Initializing secret resolver",
		slog.String("type", secretManagerType))

	switch strings.ToLower(secretManagerType) {
	case "database":
		return NewDatabaseSecretResolver(logger)
	case "infisical":
		return newInfisicalSecretResolver(logger)
	default:
		return nil, fmt.Errorf("unsupported SECRET_MANAGER_TYPE: %s (supported: database, infisical)", secretManagerType)
	}
}

// newInfisicalSecretResolver creates a new Infisical secret resolver
func newInfisicalSecretResolver(logger *slog.Logger) (*InfisicalSecretResolver, error) {
	// Get Infisical configuration from environment
	infisicalURL := os.Getenv("INFISICAL_URL")
	if infisicalURL == "" {
		infisicalURL = "http://infisical:8080" // Default for docker-compose
	}

	// Load bootstrap token from config file
	tokenPath := os.Getenv("INFISICAL_TOKEN_PATH")
	if tokenPath == "" {
		tokenPath = "/app/bootstrap/data/infisical_config.json"
	}

	// Read and parse the bootstrap config
	configData, err := os.ReadFile(tokenPath)
	if err != nil {
		logger.Warn("Could not read Infisical config file, using placeholder implementation",
			slog.String("token_path", tokenPath),
			slog.String("error", err.Error()))
		return &InfisicalSecretResolver{
			client:      nil,
			logger:      logger,
			projectID:   "default",
			environment: "dev",
		}, nil
	}

	var config InfisicalConfig
	if err := json.Unmarshal(configData, &config); err != nil {
		logger.Warn("Could not parse Infisical config file, using placeholder implementation",
			slog.String("error", err.Error()))
		return &InfisicalSecretResolver{
			client:      nil,
			logger:      logger,
			projectID:   "default",
			environment: "dev",
		}, nil
	}

	// Initialize Infisical client
	client := infisical.NewInfisicalClient(context.Background(), infisical.Config{
		SiteUrl: infisicalURL,
	})

	// Set the access token for authentication
	client.Auth().SetAccessToken(config.Identity.Credentials.Token)

	// Get project and environment from config or environment variables
	projectID := os.Getenv("INFISICAL_PROJECT_ID")
	if projectID == "" {
		projectID = config.Organization.ID // Use organization ID as project ID
	}

	environment := os.Getenv("INFISICAL_ENVIRONMENT")
	if environment == "" {
		environment = "dev" // Default environment
	}

	logger.Info("Initialized Infisical secret resolver",
		slog.String("infisical_url", infisicalURL),
		slog.String("project_id", projectID),
		slog.String("environment", environment),
		slog.String("organization", config.Organization.Name))

	return &InfisicalSecretResolver{
		client:      client,
		logger:      logger,
		projectID:   projectID,
		environment: environment,
	}, nil
}

// ResolveSecrets resolves all secrets for an MCP instance
func (sr *InfisicalSecretResolver) ResolveSecrets(instanceID string, envVars map[string]string) (map[string]string, error) {
	resolved := make(map[string]string)

	for key, value := range envVars {
		// Check if this is a secret reference or a plain value
		if strings.HasPrefix(value, "secret_ref:") {
			// This is a secret reference, resolve it from Infisical
			secretValue, err := sr.resolveSecretFromInfisical(instanceID, key)
			if err != nil {
				sr.logger.Error("Failed to resolve secret from Infisical",
					slog.String("instance_id", instanceID),
					slog.String("secret_key", key),
					slog.String("error", err.Error()))
				return nil, fmt.Errorf("failed to resolve secret %s: %w", key, err)
			}
			resolved[key] = secretValue
		} else {
			// This is a plain value, use as-is
			resolved[key] = value
		}
	}

	sr.logger.Debug("Resolved secrets for instance",
		slog.String("instance_id", instanceID),
		slog.Int("total_vars", len(envVars)),
		slog.Int("resolved_secrets", len(resolved)))

	return resolved, nil
}

// resolveSecretFromInfisical retrieves a secret from Infisical using the same pattern as Python service
func (sr *InfisicalSecretResolver) resolveSecretFromInfisical(instanceID, secretKey string) (string, error) {
	// Use the same secret key pattern as MCPEnvironmentService in Python:
	// mcp_instance_{instance_id}_{env_name}
	infisicalSecretKey := fmt.Sprintf("mcp_instance_%s_%s", instanceID, secretKey)

	sr.logger.Debug("Retrieving secret from Infisical",
		slog.String("instance_id", instanceID),
		slog.String("secret_key", secretKey),
		slog.String("infisical_key", infisicalSecretKey))

	// If client is not initialized (fallback mode), return error
	if sr.client == nil {
		return "", fmt.Errorf("Infisical client not initialized - secret resolution not available for: %s", infisicalSecretKey)
	}

	// Retrieve secret from Infisical
	secret, err := sr.client.Secrets().Retrieve(infisical.RetrieveSecretOptions{
		SecretKey:   infisicalSecretKey,
		ProjectID:   sr.projectID,
		Environment: sr.environment,
		SecretPath:  "/", // Default path
	})

	if err != nil {
		sr.logger.Error("Failed to retrieve secret from Infisical",
			slog.String("infisical_key", infisicalSecretKey),
			slog.String("project_id", sr.projectID),
			slog.String("environment", sr.environment),
			slog.String("error", err.Error()))
		return "", fmt.Errorf("failed to retrieve secret from Infisical: %w", err)
	}

	sr.logger.Info("Successfully retrieved secret from Infisical",
		slog.String("instance_id", instanceID),
		slog.String("secret_key", secretKey),
		slog.String("infisical_key", infisicalSecretKey))

	return secret.SecretValue, nil
}

// Close closes the secret resolver
func (sr *InfisicalSecretResolver) Close() error {
	sr.logger.Info("Closing Infisical secret resolver")
	// TODO: Close Infisical client if needed
	return nil
}
