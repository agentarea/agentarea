package domain

import "time"

// Managed-config markers and the platform's own owner name.
const (
	CredentialModeManaged = "managed"
	ManagedByPlatform     = "platform"
	AccessWorkspace       = "workspace"
	AccessPublic          = "public"
)

// AuthConfig is an mcp_auth_configs row without its credentials, which live
// in the secret store under SecretKey.
type AuthConfig struct {
	ID            string
	WorkspaceID   string
	CreatedBy     string
	Name          string
	Description   *string
	AuthType      string
	Config        map[string]any
	SecretKey     *string
	OpenAPIConnID *string
	MCPInstanceID *string
	CreatedAt     time.Time
	UpdatedAt     time.Time
}

// SecretKey is the secret store name of an auth config's credentials.
func SecretKeyFor(configID string) string { return "mcp_auth_cred:" + configID }

// AuthConfigNew is what a caller asks to create.
type AuthConfigNew struct {
	Name        string
	Description *string
	AuthType    string
	Config      map[string]any
	Credentials map[string]any
}

// AuthConfigPatch is what a caller asks to change; nil means unchanged.
type AuthConfigPatch struct {
	Name        *string
	Description *string
	Config      map[string]any
	Credentials map[string]any
}

// ValidateCredentials is MCPAuthService.validate_credentials.
func ValidateCredentials(authType string, creds map[string]any) error {
	switch authType {
	case "api_key":
		if !Truthy(creds["header_value"]) {
			return &Invalid{"api_key credentials require 'header_value'"}
		}
	case "bearer":
		if !Truthy(creds["token"]) {
			return &Invalid{"bearer credentials require 'token'"}
		}
	case "oauth2":
		if !Truthy(creds["client_secret"]) && !Truthy(creds["access_token"]) {
			return &Invalid{"oauth2 credentials require 'client_secret' or an existing 'access_token'"}
		}
	}
	return nil
}

// IsManaged reports a config the platform's catalog connection owns.
func IsManaged(config map[string]any) bool {
	return config != nil && config["credential_mode"] == CredentialModeManaged
}

// UsesWorkspaceReferences reports a config that names existing workspace secrets.
func UsesWorkspaceReferences(config map[string]any) bool {
	return Truthy(config["client_id_secret_name"]) || Truthy(config["client_secret_secret_name"])
}

// ValidAuthType is the check MCPAuthConfig's constructor makes.
func ValidAuthType(authType string) error {
	switch authType {
	case "api_key", "bearer", "oauth2":
		return nil
	}
	return &Invalid{"Invalid auth_type '" + authType + "'. Must be one of {'api_key', 'bearer', 'oauth2'}"}
}

// ValidateConfig is MCPAuthConfig.validate_config.
func ValidateConfig(authType string, config map[string]any) error {
	switch authType {
	case "api_key":
		if !Truthy(config["header_name"]) {
			return &Invalid{"api_key auth requires 'header_name' in config"}
		}
	case "oauth2":
		if !Truthy(config["token_url"]) {
			return &Invalid{"oauth2 auth requires 'token_url' in config"}
		}
		if Truthy(config["platform_oauth_issuer"]) {
			if config["credential_mode"] != CredentialModeManaged {
				return &Invalid{"'platform_oauth_issuer' requires credential_mode 'managed'"}
			}
			return nil
		}
		if config["credential_mode"] == CredentialModeManaged {
			return &Invalid{"managed oauth2 auth requires 'platform_oauth_issuer' in config"}
		}
		hasID := Truthy(config["client_id"])
		hasSecretName := Truthy(config["client_id_secret_name"])
		if hasID == hasSecretName {
			return &Invalid{"oauth2 auth requires exactly one of 'client_id' or 'client_id_secret_name' in config"}
		}
	}
	return nil
}

// CheckCreate is the refusal order of MCPAuthService.create before the row is written.
func CheckCreate(n AuthConfigNew) error {
	if err := ValidateCredentials(n.AuthType, n.Credentials); err != nil {
		return err
	}
	if IsManaged(n.Config) {
		return &Invalid{"Managed OAuth configs can only be created by a catalog connection"}
	}
	if UsesWorkspaceReferences(n.Config) {
		return &Invalid{"Workspace OAuth secret references can only be created by a catalog connection"}
	}
	if err := ValidAuthType(n.AuthType); err != nil {
		return err
	}
	return ValidateConfig(n.AuthType, n.Config)
}

// CheckUpdate is the catalog guard of MCPAuthService.update.
func CheckUpdate(existing map[string]any, p AuthConfigPatch) error {
	incoming := p.Config
	if !IsManaged(existing) && !IsManaged(incoming) && !UsesWorkspaceReferences(existing) && !UsesWorkspaceReferences(incoming) {
		return nil
	}
	if p.Config != nil || p.Credentials != nil {
		return &Invalid{"Catalog OAuth credentials can only be changed by reconnecting the catalog connection"}
	}
	return nil
}
