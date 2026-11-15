package domain

import (
	"strings"
	"time"
)

// Transports of an instance (MCPTransport).
const (
	TransportURL     = "url"
	TransportDocker  = "docker"
	TransportCommand = "command"
	TransportBundle  = "bundle"
)

// IsContainer reports a transport whose workload the runtime runs.
func IsContainer(transport string) bool {
	return transport == TransportDocker || transport == TransportCommand
}

// Verification statuses; liveness is verification.status.
const (
	VerifyNeverAttempted = "never_attempted"
	VerifyInProgress     = "in_progress"
	VerifySucceeded      = "succeeded"
	VerifyFailed         = "failed"
	VerificationSchema   = 1
)

// MaskedValue replaces a secret's value in every response; the webapp sends it
// back unchanged to keep the stored secret.
const MaskedValue = "******"

// SecretRefKey is the key of a {"secret_name": ...} reference.
const SecretRefKey = "secret_name"

// SecretRefConsumer is the consumer type references of an instance are staged under.
const SecretRefConsumer = "mcp_instance"

// VerificationError is verification.error.
type VerificationError struct {
	Code    string `json:"code"`
	Message string `json:"message"`
	Detail  any    `json:"detail"`
}

// Verification is mcp_server_instances.verification.
type Verification struct {
	SchemaVersion int                `json:"schema_version"`
	Status        string             `json:"status"`
	At            *string            `json:"at"`
	Error         *VerificationError `json:"error"`
}

// DefaultVerification is what a new row starts with.
func DefaultVerification() Verification {
	return Verification{SchemaVersion: VerificationSchema, Status: VerifyNeverAttempted}
}

// Instance is an mcp_server_instances row. JSON columns are decoded with
// numbers kept as written (json.Number).
type Instance struct {
	ID           string
	WorkspaceID  string
	CreatedBy    string
	Name         string
	Description  *string
	ServerSpecID string
	Transport    string
	JSONSpec     map[string]any
	Verification Verification
	// VerificationRaw is the stored object as read, for a row whose shape is not ours.
	VerificationRaw map[string]any
	LastDispatch    map[string]any
	Tools           []any
	// ToolsSet distinguishes a NULL tools column from an empty list.
	ToolsSet     bool
	Events       map[string]any
	AuthConfigID *string
	ManagedBy    *string
	Cost         map[string]any
	CreatedAt    time.Time
	UpdatedAt    time.Time
}

// PlatformManaged reports a connection the deployment supplies.
func (i Instance) PlatformManaged() bool {
	return i.ManagedBy != nil && *i.ManagedBy == ManagedByPlatform
}

// EnvVars is json_spec.env_vars: the names whose values live in the secret store.
func (i Instance) EnvVars() []string { return StringList(i.JSONSpec["env_vars"]) }

// AvailableTools is tools, falling back to the legacy json_spec.available_tools.
func (i Instance) AvailableTools() []any {
	if len(i.Tools) > 0 {
		return i.Tools
	}
	if l, ok := i.JSONSpec["available_tools"].([]any); ok {
		return l
	}
	return nil
}

// EndpointURL is a URL instance's endpoint; empty for any other transport.
func (i Instance) EndpointURL() string {
	if i.Transport != TransportURL {
		return ""
	}
	s, _ := i.JSONSpec["endpoint_url"].(string)
	return s
}

// InstanceSecretName is the secret store name of an instance env var or header.
func InstanceSecretName(instanceID, name string) string {
	return "mcp_instance_" + instanceID + "_" + name
}

// ContextSecretEnv is the env name the context-signing secret is stored under.
const ContextSecretEnv = "AGENTAREA_CONTEXT_SECRET"

// StringList is the strings of a decoded JSON list; anything else is none.
func StringList(v any) []string {
	l, ok := v.([]any)
	if !ok {
		return nil
	}
	out := make([]string, 0, len(l))
	for _, x := range l {
		if s, ok := x.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

// IsSecretRef is is_secret_ref.
func IsSecretRef(v any) bool {
	m, ok := v.(map[string]any)
	if !ok {
		return false
	}
	_, ok = m[SecretRefKey].(string)
	return ok
}

// SecretRefName is secret_ref_name: the referenced secret, "" for a literal,
// an *Invalid for an object that is not exactly a reference.
func SecretRefName(field string, v any) (string, error) {
	m, ok := v.(map[string]any)
	if !ok {
		return "", nil
	}
	name, ok := m[SecretRefKey].(string)
	if len(m) != 1 || !ok || strings.TrimSpace(name) == "" {
		return "", &Invalid{Msg: field + ` must be a string or {"secret_name": "<workspace secret>"}`}
	}
	return name, nil
}

// CarriesSecretRef is carries_secret_ref: a reference at any depth.
func CarriesSecretRef(v any) bool {
	switch t := v.(type) {
	case map[string]any:
		if _, ok := t[SecretRefKey]; ok {
			return true
		}
		for _, x := range t {
			if CarriesSecretRef(x) {
				return true
			}
		}
	case []any:
		for _, x := range t {
			if CarriesSecretRef(x) {
				return true
			}
		}
	}
	return false
}

// SpecSecretRefs is spec_secret_refs over environment and headers.
func SpecSecretRefs(spec map[string]any) (map[string]string, error) {
	refs := map[string]string{}
	for _, field := range []string{"environment", "headers"} {
		values, ok := spec[field].(map[string]any)
		if !ok {
			continue
		}
		for name, v := range values {
			secret, err := SecretRefName(name, v)
			if err != nil {
				return nil, err
			}
			if secret != "" {
				refs[name] = secret
			}
		}
	}
	return refs, nil
}

// IsMaskPlaceholder is a value a client echoed back from a masked response:
// asterisks or bullets only.
func IsMaskPlaceholder(v any) bool {
	s, ok := v.(string)
	if !ok || s == "" {
		return false
	}
	for _, r := range s {
		if r != '*' && r != '•' && r != '●' {
			return false
		}
	}
	return true
}

// EnvSchemaEntry is a normalized env_schema entry.
type EnvSchemaEntry struct {
	Name        string
	Description string
	IsSecret    bool
	IsRequired  bool
	Default     any
	HasDefault  bool
}

// NormalizeEnvSchema is normalize_env_schema.
func NormalizeEnvSchema(entries any) []EnvSchemaEntry {
	list, ok := entries.([]any)
	if !ok {
		return nil
	}
	var out []EnvSchemaEntry
	for _, e := range list {
		m, ok := e.(map[string]any)
		if !ok {
			continue
		}
		name, ok := m["name"].(string)
		if !ok || strings.TrimSpace(name) == "" {
			continue
		}
		req, has := m["isRequired"]
		if !has || req == nil {
			req = m["required"]
		}
		desc, _ := m["description"].(string)
		entry := EnvSchemaEntry{Name: name, Description: desc, IsSecret: Truthy(m["isSecret"]), IsRequired: Truthy(req)}
		if d, has := m["default"]; has && !entry.IsSecret {
			entry.Default, entry.HasDefault = d, true
		}
		out = append(out, entry)
	}
	return out
}

// EnvSchemaJSON renders entries as the stored/returned list.
func EnvSchemaJSON(entries []EnvSchemaEntry) []any {
	out := make([]any, 0, len(entries))
	for _, e := range entries {
		m := map[string]any{"name": e.Name, "description": e.Description, "isSecret": e.IsSecret,
			"isRequired": e.IsRequired, "required": e.IsRequired}
		if e.HasDefault {
			m["default"] = e.Default
		}
		out = append(out, m)
	}
	return out
}

// SecretNamesOf is _instance_secret_env_names: the schema's secret names
// plus every environment/header name the schema does not know (secret by default).
func SecretNamesOf(schema []EnvSchemaEntry, spec map[string]any) map[string]bool {
	known := map[string]bool{}
	secret := map[string]bool{}
	for _, e := range schema {
		known[e.Name] = true
		if e.IsSecret {
			secret[e.Name] = true
		}
	}
	for _, field := range []string{"environment", "headers"} {
		if values, ok := spec[field].(map[string]any); ok {
			for name := range values {
				if !known[name] {
					secret[name] = true
				}
			}
		}
	}
	return secret
}

// MaskedSpec is the json_spec a response shows: every secret value of
// environment and headers replaced by MaskedValue unless it is a reference,
// and every stored secret name present.
func MaskedSpec(spec map[string]any, secretNames map[string]bool) map[string]any {
	out := make(map[string]any, len(spec))
	for k, v := range spec {
		out[k] = v
	}
	listed := map[string]bool{}
	for _, n := range StringList(spec["env_vars"]) {
		listed[n] = true
	}
	for _, field := range []string{"environment", "headers"} {
		values, ok := spec[field].(map[string]any)
		if !ok {
			continue
		}
		masked := make(map[string]any, len(values))
		for name, v := range values {
			if (secretNames[name] || listed[name]) && !IsSecretRef(v) {
				masked[name] = MaskedValue
			} else {
				masked[name] = v
			}
		}
		for name := range listed {
			if _, ok := masked[name]; !ok {
				masked[name] = MaskedValue
			}
		}
		out[field] = masked
	}
	return out
}
