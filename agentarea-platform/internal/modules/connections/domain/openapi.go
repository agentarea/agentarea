package domain

import "time"

// Header is one entry of custom_headers as stored: a secret's value lives in
// the secret store, so a secret entry carries no value.
type Header struct {
	Name   string
	Secret bool
	Value  *string
}

// QueryParam is one entry of custom_query_params, stored like Header.
type QueryParam struct {
	Name   string
	Secret bool
	Value  *string
}

// Tool is one entry of available_tools as stored.
type Tool struct {
	Name        string
	Description string
	InputSchema map[string]any
}

// Connection is an openapi_connections row.
type Connection struct {
	ID             string
	WorkspaceID    string
	CreatedBy      string
	Name           string
	Description    *string
	SpecURL        *string
	BaseURL        string
	AuthConfigID   *string
	RegistryItemID *string
	CustomHeaders  []Header
	CustomQuery    []QueryParam
	URLVariables   []string
	AvailableTools []Tool
	Status         string
	LastDispatch   map[string]any
	Cost           map[string]any
	ManagedBy      *string
	CreatedAt      time.Time
	UpdatedAt      time.Time
	// SpecContent and AllowedAuthOrigins are read by the full reads only.
	// SpecContent keeps the stored key order (wirejson objects); nil is NULL.
	SpecContent        any
	AllowedAuthOrigins []string
}

// PlatformManaged is a connection the platform runs, for every workspace.
func (c Connection) PlatformManaged() bool {
	return c.ManagedBy != nil && *c.ManagedBy == ManagedByPlatform
}

// VisibleBaseURL is the address a tenant may see: nil for a platform-managed
// connection, whose base URL is the deployment's topology.
func (c Connection) VisibleBaseURL() *string {
	if c.ManagedBy != nil && *c.ManagedBy == ManagedByPlatform {
		return nil
	}
	b := c.BaseURL
	return &b
}

// Sharing is who may call through a connection, as the list and detail show it.
type Sharing struct {
	Personal bool
	IsOwner  bool
}

// SecretHeaderKey is the secret name of a header value (service._secret_key).
func SecretHeaderKey(connID, header string) string {
	return "openapi:" + connID + ":header:" + header
}

// SecretURLVarKey is the secret name of a URL variable value.
func SecretURLVarKey(connID, variable string) string {
	return "openapi:" + connID + ":url_var:" + variable
}

// SecretQueryKey is the secret name of a query parameter value.
func SecretQueryKey(connID, param string) string {
	return "openapi:" + connID + ":query:" + param
}

// SecretNames is every secret name a connection's row refers to.
func (c Connection) SecretNames() []string {
	var out []string
	for _, h := range c.CustomHeaders {
		if h.Secret {
			out = append(out, SecretHeaderKey(c.ID, h.Name))
		}
	}
	for _, p := range c.CustomQuery {
		if p.Secret {
			out = append(out, SecretQueryKey(c.ID, p.Name))
		}
	}
	for _, v := range c.URLVariables {
		out = append(out, SecretURLVarKey(c.ID, v))
	}
	return out
}
