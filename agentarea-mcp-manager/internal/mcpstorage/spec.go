// Package mcpstorage serves MCP instances a small object store: one prefix per
// instance under its workspace, written only through conditional requests so
// any number of stateless app processes can share it without lost updates.
//
// An instance whose spec opts in with `"storage": {"enabled": true}` reaches it
// at {MCP_MANAGER_URL}/mcp/{MCP_INSTANCE_ID}/storage with the bearer token the
// manager injects as MCP_STORAGE_TOKEN.
package mcpstorage

import (
	"errors"
	"fmt"
	"net/url"
	"strings"
	"time"

	"github.com/agentarea/mcp-manager/internal/activationauth"
	"github.com/agentarea/mcp-manager/internal/models"
)

// SpecKey is the json_spec key an MCP server spec opts in with.
const SpecKey = "storage"

const (
	// TokenTTL is the lifetime of the token minted at every container create.
	TokenTTL = 30 * 24 * time.Hour
	// MaxObjectBytes bounds one object's body.
	MaxObjectBytes = 64 << 20
)

// Enabled reports whether a json_spec opts into storage. The only accepted
// value is {"enabled": true}; an absent (or JSON null) key means no. Anything
// else is an error, so a typo cannot silently start an app without the storage
// it was written against.
func Enabled(spec map[string]any) (bool, error) {
	raw, ok := spec[SpecKey]
	if !ok || raw == nil {
		return false, nil
	}
	value, ok := raw.(map[string]any)
	if !ok {
		return false, fmt.Errorf(`json_spec.%s must be {"enabled": true}`, SpecKey)
	}
	enabled, ok := value["enabled"].(bool)
	if len(value) != 1 || !ok || !enabled {
		return false, fmt.Errorf(`json_spec.%s must be exactly {"enabled": true}`, SpecKey)
	}
	return true, nil
}

// ParseManagerURL checks the manager URL as instance containers reach it. An
// empty value is allowed: an instance that opts in is then refused.
func ParseManagerURL(raw string) (string, error) {
	if raw == "" {
		return "", nil
	}
	parsed, err := url.Parse(raw)
	if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host == "" {
		return "", errors.New("MCP_MANAGER_URL must be an absolute http(s) URL")
	}
	if parsed.RawQuery != "" || parsed.Fragment != "" || parsed.User != nil {
		return "", errors.New("MCP_MANAGER_URL must not carry credentials, a query or a fragment")
	}
	return strings.TrimRight(raw, "/"), nil
}

// Issuer hands opted-in instances their storage environment.
type Issuer struct {
	secret     []byte
	managerURL string
	now        func() time.Time
}

// NewIssuer signs with the manager's gateway secret and hands out managerURL,
// the manager as instance containers reach it.
func NewIssuer(secret []byte, managerURL string) *Issuer {
	return &Issuer{secret: secret, managerURL: managerURL, now: time.Now}
}

// Environment returns the variables to add to the instance container, or nil
// when the instance does not opt in. A fresh token is minted on every call.
func (i *Issuer) Environment(instance *models.MCPServerInstance) (map[string]string, error) {
	if instance == nil {
		return nil, errors.New("MCP instance is required")
	}
	enabled, err := Enabled(instance.JSONSpec)
	if err != nil || !enabled {
		return nil, err
	}
	if i == nil || i.managerURL == "" {
		return nil, fmt.Errorf("MCP instance %s opts into storage, but this manager has no MCP_MANAGER_URL to give it", instance.InstanceID)
	}
	token, err := activationauth.Sign(i.secret, activationauth.ScopeStorage, identity(instance.WorkspaceID, instance.InstanceID), activationauth.BodySHA256(nil), i.now(), TokenTTL)
	if err != nil {
		return nil, fmt.Errorf("mint storage token for MCP instance %s: %w", instance.InstanceID, err)
	}
	return map[string]string{"MCP_MANAGER_URL": i.managerURL, "MCP_STORAGE_TOKEN": token}, nil
}

func identity(workspaceID, instanceID string) activationauth.Identity {
	return activationauth.Identity{WorkspaceID: workspaceID, InstanceID: instanceID}
}
