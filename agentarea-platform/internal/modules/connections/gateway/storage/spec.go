// Package storage serves MCP instances a small object store: one prefix per
// instance under its workspace, written only through conditional requests so
// any number of stateless processes can share it without lost updates.
//
// An instance whose spec opts in with "storage": {"enabled": true} reaches it
// at {MCP_MANAGER_URL}/mcp/{MCP_INSTANCE_ID}/storage with the bearer token
// handed to it as MCP_STORAGE_TOKEN.
package storage

import (
	"errors"
	"fmt"
	"net/url"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
)

// SpecKey is the json_spec key an MCP server spec opts in with.
const SpecKey = "storage"

const (
	// TokenTTL is the lifetime of the token minted at every workload create.
	TokenTTL = 30 * 24 * time.Hour
	// MaxObjectBytes bounds one object's body.
	MaxObjectBytes = 64 << 20
)

// Container environment the issuer hands an opted-in workload.
const (
	EnvManagerURL   = "MCP_MANAGER_URL"
	EnvStorageToken = "MCP_STORAGE_TOKEN"
)

// ConditionalWrites is who enforces a write's precondition.
type ConditionalWrites string

const (
	// NativeConditionalWrites hands the precondition to the object store,
	// which checks it atomically with the write.
	NativeConditionalWrites ConditionalWrites = "native"
	// EmulatedConditionalWrites checks it here, under a per-object lock, for a
	// store that refuses or ignores conditional writes (Timeweb S3). Safe only
	// with a single writer process.
	EmulatedConditionalWrites ConditionalWrites = "emulated"
)

// Config is the storage API's environment.
type Config struct {
	// ManagerURL is the MCP role as workload containers reach it; empty
	// refuses every instance that opts in.
	ManagerURL string
	Writes     ConditionalWrites
}

// LoadConfig reads AGENTAREA_MCP_MANAGER_URL and AGENTAREA_S3_CONDITIONAL_WRITES.
func LoadConfig(l *config.Loader) Config {
	raw, _ := l.OptionalEnv("AGENTAREA_MCP_MANAGER_URL")
	managerURL, err := ParseManagerURL(raw)
	if err != nil {
		l.Fail("AGENTAREA_MCP_MANAGER_URL", err)
	}
	writes := l.OneOfEnv("AGENTAREA_S3_CONDITIONAL_WRITES", string(NativeConditionalWrites),
		string(NativeConditionalWrites), string(EmulatedConditionalWrites))
	return Config{ManagerURL: managerURL, Writes: ConditionalWrites(writes)}
}

// Enabled reports whether a json_spec opts into storage. The only accepted
// value is {"enabled": true}; an absent or null key means no. Anything else
// is an error, so a typo cannot start an app without the storage it expects.
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

// ParseManagerURL checks the URL workload containers reach the MCP role at.
// An empty value is allowed: an instance that opts in is then refused.
func ParseManagerURL(raw string) (string, error) {
	if raw == "" {
		return "", nil
	}
	parsed, err := url.Parse(raw)
	if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host == "" {
		return "", errors.New("AGENTAREA_MCP_MANAGER_URL must be an absolute http(s) URL")
	}
	if parsed.RawQuery != "" || parsed.Fragment != "" || parsed.User != nil {
		return "", errors.New("AGENTAREA_MCP_MANAGER_URL must not carry credentials, a query or a fragment")
	}
	return strings.TrimRight(raw, "/"), nil
}

// Issuer hands opted-in instances their storage environment.
type Issuer struct {
	secret     []byte
	managerURL string
	now        func() time.Time
}

// NewIssuer signs with the gateway secret (AGENTAREA_MCP_GATEWAY_SECRET) and
// hands out managerURL.
func NewIssuer(secret []byte, managerURL string) *Issuer {
	return &Issuer{secret: secret, managerURL: managerURL, now: time.Now}
}

// Environment is the variables to add to the instance's workload, or nil when
// it does not opt in. A fresh token is minted on every call.
func (i *Issuer) Environment(instanceID, workspaceID string, spec map[string]any) (map[string]string, error) {
	enabled, err := Enabled(spec)
	if err != nil || !enabled {
		return nil, err
	}
	if i == nil || i.managerURL == "" {
		return nil, fmt.Errorf("MCP instance %s opts into storage, but AGENTAREA_MCP_MANAGER_URL is not set, so there is no MCP_MANAGER_URL to give it", instanceID)
	}
	token, err := signToken(i.secret, workspaceID, instanceID, i.now(), TokenTTL)
	if err != nil {
		return nil, fmt.Errorf("mint storage token for MCP instance %s: %w", instanceID, err)
	}
	return map[string]string{EnvManagerURL: i.managerURL, EnvStorageToken: token}, nil
}
