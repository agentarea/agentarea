// Package mcpcontext gives an MCP instance the key that proves who a call is for.
//
// The platform signs every call to an instance whose spec opts in with
// `"context": {"enabled": true}` as an HS256 token in the X-AgentArea-Context
// header (docs/reference/mcp-tool-call-context.md). For instances the
// platform runs, the key is derived from the gateway secret both sides hold
// and the instance id, so nothing is stored and no owner has to set it; the
// manager hands it to the container as MCP_CONTEXT_KEY.
package mcpcontext

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"

	"github.com/agentarea/mcp-manager/internal/models"
)

// SpecKey is the json_spec key an MCP server spec opts in with.
const SpecKey = "context"

// KeyEnv is the variable the instance container reads the key from.
const KeyEnv = "MCP_CONTEXT_KEY"

// derivation separates this key from every other use of the gateway secret.
// agentarea_mcp.tool_context.derived_context_key computes the same value.
const derivation = "agentarea/mcp-context/v1:"

// Enabled reports whether a json_spec opts into caller context. The only
// accepted value is {"enabled": true}; an absent (or JSON null) key means no.
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

// Key is the instance's signing key: hex HMAC-SHA256 of the instance id under the gateway secret.
func Key(secret []byte, instanceID string) string {
	mac := hmac.New(sha256.New, secret)
	mac.Write([]byte(derivation + instanceID))
	return hex.EncodeToString(mac.Sum(nil))
}

// Issuer hands opted-in instances their context key.
type Issuer struct {
	secret []byte
}

// NewIssuer derives keys from the manager's gateway secret.
func NewIssuer(secret []byte) *Issuer {
	return &Issuer{secret: secret}
}

// Environment returns the variables to add to the instance container, or nil
// when the instance does not opt in.
func (i *Issuer) Environment(instance *models.MCPServerInstance) (map[string]string, error) {
	if instance == nil {
		return nil, errors.New("MCP instance is required")
	}
	enabled, err := Enabled(instance.JSONSpec)
	if err != nil || !enabled {
		return nil, err
	}
	if i == nil || len(i.secret) == 0 {
		return nil, fmt.Errorf("MCP instance %s opts into caller context, but this manager has no gateway secret to derive its key from", instance.InstanceID)
	}
	return map[string]string{KeyEnv: Key(i.secret, instance.InstanceID)}, nil
}
