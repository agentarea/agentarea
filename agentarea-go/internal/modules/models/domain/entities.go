package domain

import "time"

// ManagedByPlatform marks a configuration whose credentials the deployment supplies.
const ManagedByPlatform = "platform"

// Config is a provider_configs row. APIKey is the NAME of the secret holding the key.
type Config struct {
	ID, ProviderSpecID     string
	Name                   string
	Description            *string
	APIKey                 *string
	EndpointURL            *string
	IsActive, IsPublic     bool
	WorkspaceID, CreatedBy string
	CreatedAt, UpdatedAt   time.Time
	APIKeySecretID         *string
	ManagedBy              *string
}

// PlatformManaged: the deployment supplies the credentials; no tenant writes it.
func (c Config) PlatformManaged() bool {
	return c.ManagedBy != nil && *c.ManagedBy == ManagedByPlatform
}

// Instance is a model_instances row.
type Instance struct {
	ID, ProviderConfigID, ModelSpecID string
	Name                              string
	Description                       *string
	IsActive, IsPublic                bool
	WorkspaceID, CreatedBy            string
	CreatedAt, UpdatedAt              time.Time
	Tags                              []string
}

// OwnSecretName is the secret a configuration mints for its own key.
func OwnSecretName(configID string) string { return "provider_config_" + configID }

// Opt is a patch field: Set when the key was sent, Value nil when it was null.
type Opt[T any] struct {
	Set   bool
	Value *T
}

// NewConfig is ProviderConfigCreate after validation: APIKey stripped, "" absent.
type NewConfig struct {
	ProviderSpecID string
	Name           string
	APIKey         *string
	APIKeySecretID *string
	EndpointURL    *string
	Description    *string
	IsPublic       bool
}

// ConfigPatch is ProviderConfigUpdate: only Set fields are applied.
type ConfigPatch struct {
	Name, Description, EndpointURL, APIKey, APIKeySecretID Opt[string]
	IsActive, IsPublic                                     Opt[bool]
}

// NewInstance is ModelInstanceCreate.
type NewInstance struct {
	ProviderConfigID, ModelSpecID string
	Name                          string
	Description                   *string
	IsPublic                      bool
}
