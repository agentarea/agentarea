package sandboxruntime

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	opensandbox "github.com/alibaba/OpenSandbox/sdks/sandbox/go"
	redis "github.com/redis/go-redis/v9"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/supervisor/runtimeinfo"
)

// ControlPolicy is the provider-neutral lease and record policy. Python
// callers never send a provider name; changing providers is an operator-side
// configuration change.
type ControlPolicy struct {
	TaskLeaseTTL                time.Duration
	TaskIdleTTL                 time.Duration
	ProviderProvisioningTimeout time.Duration
	SessionRecordTTL            time.Duration
}

type WorkspaceLimits struct {
	// MaxFiles is the maximum number of non-root filesystem entries in a live
	// workspace. Durable manifests contain files only, while live sandboxes also
	// count directories and symlinks so none can bypass the inode budget.
	MaxFiles     int
	MaxFileBytes int64
	MaxBytes     int64
}

// Config is the runtime's environment: the control policy, the workspace data
// plane and, for an external provider, how to reach it.
type Config struct {
	Policy      ControlPolicy
	Workspace   WorkspaceProvider
	RedisPrefix string
	External    ExternalConfig
}

// ExternalConfig is read only when the provider is opensandbox, e2b or cube.
// Lease, timeout, storage and internet fields of OpenSandbox and E2B are set
// from the policy and the workspace limits when the runtime is built.
type ExternalConfig struct {
	Manifest      *runtimeinfo.Manifest
	AllowInternet bool
	OpenSandbox   OpenSandboxConfig
	E2B           E2BConfig
}

// LoadConfig reads the runtime of provider (AGENTAREA_SANDBOX_PROVIDER,
// lowercased); l reports what is missing or malformed.
func LoadConfig(l *config.Loader, provider string) Config {
	c := Config{
		Policy:      LoadControlPolicy(l),
		Workspace:   LoadWorkspaceProvider(l),
		RedisPrefix: l.StringEnv("AGENTAREA_SANDBOX_REDIS_PREFIX", ""),
	}
	switch provider {
	case "opensandbox", "e2b", "cube":
		c.External = loadExternalConfig(l, provider)
	}
	return c
}

// LoadControlPolicy reads the lease and record policy; none has a default.
func LoadControlPolicy(l *config.Loader) ControlPolicy {
	leaseTTL, okLease := requiredDuration(l, "AGENTAREA_SANDBOX_LEASE_TTL", false)
	idleTTL, okIdle := requiredDuration(l, "AGENTAREA_SANDBOX_IDLE_TTL", true)
	provisioningTimeout, okProvision := requiredDuration(l, "AGENTAREA_SANDBOX_PROVISION_TIMEOUT", false)
	sessionTTL, okSession := requiredDuration(l, "AGENTAREA_SANDBOX_SESSION_TTL", false)
	policy := ControlPolicy{
		TaskLeaseTTL: leaseTTL, TaskIdleTTL: idleTTL,
		ProviderProvisioningTimeout: provisioningTimeout, SessionRecordTTL: sessionTTL,
	}
	if okLease && okIdle && okProvision && okSession {
		if err := policy.validate(); err != nil {
			l.Fail("AGENTAREA_SANDBOX_SESSION_TTL", err)
		}
	}
	return policy
}

func (policy ControlPolicy) validate() error {
	if policy.TaskLeaseTTL <= 0 {
		return fmt.Errorf("AGENTAREA_SANDBOX_LEASE_TTL must be positive")
	}
	if policy.TaskIdleTTL < 0 {
		return fmt.Errorf("AGENTAREA_SANDBOX_IDLE_TTL must be non-negative")
	}
	if policy.ProviderProvisioningTimeout <= 0 {
		return fmt.Errorf("AGENTAREA_SANDBOX_PROVISION_TIMEOUT must be positive")
	}
	longestProviderLease := policy.TaskLeaseTTL
	if policy.TaskIdleTTL > longestProviderLease {
		longestProviderLease = policy.TaskIdleTTL
	}
	provisioningFenceTTL := policy.TaskLeaseTTL + policy.ProviderProvisioningTimeout
	if provisioningFenceTTL > longestProviderLease {
		longestProviderLease = provisioningFenceTTL
	}
	// A create outcome can remain unknown for the complete provider request
	// timeout, and its remote lease may start only at the end of that interval.
	// The durable intent must therefore outlive their sum as well as idle leases.
	if policy.SessionRecordTTL <= longestProviderLease {
		return fmt.Errorf("AGENTAREA_SANDBOX_SESSION_TTL must be greater than AGENTAREA_SANDBOX_IDLE_TTL and AGENTAREA_SANDBOX_LEASE_TTL + AGENTAREA_SANDBOX_PROVISION_TIMEOUT")
	}
	return nil
}

// LoadWorkspaceProvider reads the workspace data plane. There is no default:
// running without a declared workspace provider would silently drop task
// inputs and published artifacts.
func LoadWorkspaceProvider(l *config.Loader) WorkspaceProvider {
	switch value := l.StringEnv("AGENTAREA_SANDBOX_STORAGE", ""); value {
	case string(WorkspaceProviderS3):
		return WorkspaceProviderS3
	case "":
		l.Fail("AGENTAREA_SANDBOX_STORAGE", errors.New("is required; supported value: s3"))
	default:
		l.Fail("AGENTAREA_SANDBOX_STORAGE", fmt.Errorf("unsupported value %q; supported value: s3", value))
	}
	return ""
}

func loadExternalConfig(l *config.Loader, provider string) ExternalConfig {
	c := ExternalConfig{Manifest: loadExternalManifest(l), AllowInternet: requiredBool(l, "AGENTAREA_SANDBOX_ALLOW_INTERNET")}
	switch provider {
	case "opensandbox":
		allowInsecure := strictBool(l, "AGENTAREA_SANDBOX_OSB_INSECURE", false)
		allowWeakDev := strictBool(l, "AGENTAREA_SANDBOX_OSB_WEAK_ISOLATION", false)
		apiKey := l.StringEnv("AGENTAREA_SANDBOX_OSB_API_KEY", "")
		if apiKey == "" && !allowInsecure {
			l.Fail("AGENTAREA_SANDBOX_OSB_API_KEY", errors.New("is required unless AGENTAREA_SANDBOX_OSB_INSECURE=true"))
		}
		useProxy := strictBool(l, "AGENTAREA_SANDBOX_OSB_SERVER_PROXY", true)
		secureAccess := strictBool(l, "AGENTAREA_SANDBOX_OSB_SECURE_ACCESS", true)
		retryConfig := opensandbox.DefaultRetryConfig()
		c.OpenSandbox = OpenSandboxConfig{
			Connection: opensandbox.ConnectionConfig{
				Domain:         l.StringEnv("AGENTAREA_SANDBOX_OSB_URL", ""),
				APIKey:         apiKey,
				AuthHeader:     l.StringEnv("AGENTAREA_SANDBOX_OSB_AUTH_HEADER", "OPEN-SANDBOX-API-KEY"),
				UseServerProxy: useProxy,
				Retry:          &retryConfig,
			},
			Image:                 l.StringEnv("AGENTAREA_SANDBOX_OSB_IMAGE", ""),
			Entrypoint:            stringSliceJSON(l, "AGENTAREA_SANDBOX_OSB_ENTRYPOINT"),
			ResourceCPU:           l.StringEnv("AGENTAREA_SANDBOX_CPU", "500m"),
			ResourceMemory:        l.StringEnv("AGENTAREA_SANDBOX_MEMORY", "512Mi"),
			ResourceRequestCPU:    l.StringEnv("AGENTAREA_SANDBOX_CPU_REQUEST", ""),
			ResourceRequestMemory: l.StringEnv("AGENTAREA_SANDBOX_MEMORY_REQUEST", ""),
			StorageLimit:          l.StringEnv("AGENTAREA_SANDBOX_DISK_LIMIT", ""),
			StorageRequest:        l.StringEnv("AGENTAREA_SANDBOX_DISK_REQUEST", ""),
			Isolation:             l.StringEnv("AGENTAREA_SANDBOX_OSB_ISOLATION", ""),
			RuntimeIdentity:       l.StringEnv("AGENTAREA_SANDBOX_OSB_IDENTITY", ""),
			AllowWeakDev:          allowWeakDev,
			AllowInsecure:         allowInsecure,
			SecureAccess:          &secureAccess,
			EgressMode:            l.StringEnv("AGENTAREA_SANDBOX_OSB_EGRESS", ""),
		}
	case "e2b", "cube":
		prefix := "AGENTAREA_SANDBOX_" + strings.ToUpper(provider) + "_"
		c.E2B = E2BConfig{
			ProviderName:    provider,
			APIURL:          l.StringEnv(prefix+"URL", ""),
			APIKey:          l.StringEnv(prefix+"API_KEY", ""),
			SandboxURL:      l.StringEnv(prefix+"SANDBOX_URL", ""),
			Template:        l.StringEnv(prefix+"TEMPLATE", ""),
			AllowInsecure:   strictBool(l, prefix+"INSECURE", false),
			Isolation:       l.StringEnv(prefix+"ISOLATION", ""),
			RuntimeIdentity: l.StringEnv(prefix+"IDENTITY", ""),
			AttestationPath: l.StringEnv(prefix+"ATTESTATION", DefaultIsolationAttestationPath),
		}
	}
	return c
}

// New selects exactly one sandbox data plane: builtin for a built-in
// provider, else the external provider cfg configures, reached over transport.
func New(builtin ManagedRuntime, redisClient *redis.Client, providerName string, cfg Config, workspaceLimits WorkspaceLimits, transport http.RoundTripper) (ManagedRuntime, string, error) {
	policy := cfg.Policy
	if err := policy.validate(); err != nil {
		return nil, "", fmt.Errorf("sandbox control policy is invalid: %w", err)
	}
	if workspaceLimits.MaxFiles <= 0 || workspaceLimits.MaxFileBytes <= 0 || workspaceLimits.MaxBytes < workspaceLimits.MaxFileBytes {
		return nil, "", fmt.Errorf("sandbox workspace limits are invalid")
	}
	switch providerName {
	case "kubernetes", "docker", "agentarea":
		if builtin == nil {
			return nil, "", fmt.Errorf("AGENTAREA_SANDBOX_PROVIDER=%s requires an AgentArea sandbox backend", providerName)
		}
		return builtin, providerName, nil
	case "opensandbox", "e2b", "cube":
	default:
		return nil, "", fmt.Errorf("unsupported AGENTAREA_SANDBOX_PROVIDER=%q; expected kubernetes, docker, opensandbox, e2b, or cube", providerName)
	}
	if transport == nil {
		return nil, "", fmt.Errorf("sandbox provider %s needs an outbound transport", providerName)
	}

	store, err := NewSessionStore(redisClient, cfg.RedisPrefix, policy.SessionRecordTTL)
	if err != nil {
		return nil, "", err
	}
	external := cfg.External
	if external.Manifest == nil {
		return nil, "", fmt.Errorf("external sandbox provider requires AGENTAREA_SANDBOX_MANIFEST_PATH or AGENTAREA_SANDBOX_MANIFEST_JSON")
	}

	var provider ExternalProvider
	switch providerName {
	case "opensandbox":
		osb := external.OpenSandbox
		osb.Connection.RequestTimeout = policy.ProviderProvisioningTimeout
		guarded, err := withNISTPeerMinimums(transport)
		if err != nil {
			return nil, "", err
		}
		osb.Connection.HTTPClient = &http.Client{Transport: guarded, Timeout: policy.ProviderProvisioningTimeout}
		osb.ResourceStorage = strconv.FormatInt(workspaceLimits.MaxBytes, 10)
		osb.LeaseTTL = policy.TaskLeaseTTL
		osb.AllowInternetAccess = external.AllowInternet
		provider, err = NewOpenSandboxProvider(osb)
		if err != nil {
			return nil, "", err
		}
	case "e2b", "cube":
		e2b := external.E2B
		e2b.LeaseTTL = policy.TaskLeaseTTL
		e2b.RequestTimeout = policy.ProviderProvisioningTimeout
		e2b.AllowInternetAccess = external.AllowInternet
		provider, err = NewE2BProvider(e2b, transport)
		if err != nil {
			return nil, "", err
		}
	}

	manager, err := NewManager(provider, store, policy.TaskLeaseTTL, policy.TaskIdleTTL, external.Manifest, workspaceLimits)
	if err != nil {
		return nil, "", err
	}
	if lister, ok := provider.(ExternalSandboxLister); ok {
		return &managerWithInventory{Manager: manager, lister: lister}, providerName, nil
	}
	return manager, providerName, nil
}

func loadExternalManifest(l *config.Loader) *runtimeinfo.Manifest {
	manifestPath := l.StringEnv("AGENTAREA_SANDBOX_MANIFEST_PATH", "")
	manifestJSON := l.StringEnv("AGENTAREA_SANDBOX_MANIFEST_JSON", "")
	if manifestPath != "" && manifestJSON != "" {
		l.Fail("AGENTAREA_SANDBOX_MANIFEST_PATH", errors.New("and AGENTAREA_SANDBOX_MANIFEST_JSON are mutually exclusive"))
		return nil
	}
	if manifestPath == "" && manifestJSON == "" {
		l.Fail("AGENTAREA_SANDBOX_MANIFEST_PATH", errors.New("or AGENTAREA_SANDBOX_MANIFEST_JSON is required by an external sandbox provider"))
		return nil
	}
	var manifest *runtimeinfo.Manifest
	var err error
	name := "AGENTAREA_SANDBOX_MANIFEST_PATH"
	if manifestPath != "" {
		manifest, err = runtimeinfo.Load(manifestPath)
	} else {
		name = "AGENTAREA_SANDBOX_MANIFEST_JSON"
		manifest, err = decodeManifestJSON(manifestJSON)
	}
	if err != nil {
		l.Fail(name, fmt.Errorf("sandbox runtime manifest: %w", err))
		return nil
	}
	return manifest
}

func decodeManifestJSON(value string) (*runtimeinfo.Manifest, error) {
	decoder := json.NewDecoder(bytes.NewBufferString(value))
	decoder.DisallowUnknownFields()
	var manifest runtimeinfo.Manifest
	if err := decoder.Decode(&manifest); err != nil {
		return nil, fmt.Errorf("decode runtime manifest: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); err != io.EOF {
		return nil, fmt.Errorf("decode runtime manifest: trailing data")
	}
	if err := manifest.Validate(); err != nil {
		return nil, err
	}
	return &manifest, nil
}

// requiredDuration is a Go duration that must be set and positive, or
// non-negative when zero is allowed.
func requiredDuration(l *config.Loader, name string, zero bool) (time.Duration, bool) {
	value, ok := l.OptionalEnv(name)
	if !ok {
		l.Fail(name, config.ErrMissing)
		return 0, false
	}
	duration, err := time.ParseDuration(value)
	switch {
	case err != nil || duration < 0:
	case duration > 0 || zero:
		return duration, true
	}
	if zero {
		l.Fail(name, errors.New("must be a non-negative duration"))
	} else {
		l.Fail(name, errors.New("must be a positive duration"))
	}
	return 0, false
}

func strictBool(l *config.Loader, name string, fallback bool) bool {
	value, ok := l.OptionalEnv(name)
	if !ok {
		return fallback
	}
	parsed, err := strconv.ParseBool(value)
	if err != nil {
		l.Fail(name, errors.New("must be true or false"))
	}
	return parsed
}

func requiredBool(l *config.Loader, name string) bool {
	if _, ok := l.OptionalEnv(name); !ok {
		l.Fail(name, config.ErrMissing)
		return false
	}
	return strictBool(l, name, false)
}

func stringSliceJSON(l *config.Loader, name string) []string {
	value, ok := l.OptionalEnv(name)
	if !ok {
		return nil
	}
	var result []string
	if err := json.Unmarshal([]byte(value), &result); err != nil {
		l.Fail(name, fmt.Errorf("must be a JSON string array: %w", err))
	}
	return result
}
