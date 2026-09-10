package sandboxruntime

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"
	"time"

	opensandbox "github.com/alibaba/OpenSandbox/sdks/sandbox/go"
	redis "github.com/go-redis/redis/v8"

	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
)

// NewFromEnv selects exactly one sandbox data plane for this deployment.
// Python callers never send a provider name; changing providers is an
// operator-side configuration change.
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

func LoadControlPolicyFromEnv() (ControlPolicy, error) {
	leaseTTL, err := requiredDurationEnv("AGENTAREA_SBX_LEASE_TTL")
	if err != nil {
		return ControlPolicy{}, err
	}
	idleTTL, err := requiredNonNegativeDurationEnv("AGENTAREA_SBX_IDLE_TTL")
	if err != nil {
		return ControlPolicy{}, err
	}
	provisioningTimeout, err := requiredDurationEnv("AGENTAREA_SBX_PROVISION_TIMEOUT")
	if err != nil {
		return ControlPolicy{}, err
	}
	sessionTTL, err := requiredDurationEnv("AGENTAREA_SBX_SESSION_TTL")
	if err != nil {
		return ControlPolicy{}, err
	}
	policy := ControlPolicy{
		TaskLeaseTTL: leaseTTL, TaskIdleTTL: idleTTL,
		ProviderProvisioningTimeout: provisioningTimeout, SessionRecordTTL: sessionTTL,
	}
	if err := policy.validate(); err != nil {
		return ControlPolicy{}, err
	}
	return policy, nil
}

func (policy ControlPolicy) validate() error {
	if policy.TaskLeaseTTL <= 0 {
		return fmt.Errorf("AGENTAREA_SBX_LEASE_TTL must be positive")
	}
	if policy.TaskIdleTTL < 0 {
		return fmt.Errorf("AGENTAREA_SBX_IDLE_TTL must be non-negative")
	}
	if policy.ProviderProvisioningTimeout <= 0 {
		return fmt.Errorf("AGENTAREA_SBX_PROVISION_TIMEOUT must be positive")
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
		return fmt.Errorf("AGENTAREA_SBX_SESSION_TTL must be greater than AGENTAREA_SBX_IDLE_TTL and AGENTAREA_SBX_LEASE_TTL + AGENTAREA_SBX_PROVISION_TIMEOUT")
	}
	return nil
}

// LoadWorkspaceProviderFromEnv resolves the workspace data plane at composition
// time. There is no default: running without a declared workspace provider
// would silently drop task inputs and published artifacts.
func LoadWorkspaceProviderFromEnv() (WorkspaceProvider, error) {
	switch value := os.Getenv("AGENTAREA_SBX_STORAGE"); value {
	case string(WorkspaceProviderS3):
		return WorkspaceProviderS3, nil
	case "":
		return "", fmt.Errorf("AGENTAREA_SBX_STORAGE is required; supported value: s3")
	default:
		return "", fmt.Errorf("unsupported AGENTAREA_SBX_STORAGE=%q; supported value: s3", value)
	}
}

func NewFromEnv(_ context.Context, builtin ManagedRuntime, redisClient *redis.Client, defaultProvider string, policy ControlPolicy, workspaceLimits WorkspaceLimits) (ManagedRuntime, string, error) {
	if err := policy.validate(); err != nil {
		return nil, "", fmt.Errorf("sandbox control policy is invalid: %w", err)
	}
	if workspaceLimits.MaxFiles <= 0 || workspaceLimits.MaxFileBytes <= 0 || workspaceLimits.MaxBytes < workspaceLimits.MaxFileBytes {
		return nil, "", fmt.Errorf("sandbox workspace limits are invalid")
	}
	providerName := strings.ToLower(strings.TrimSpace(os.Getenv("AGENTAREA_SBX_PROVIDER")))
	if providerName == "" {
		providerName = defaultProvider
	}
	switch providerName {
	case "kubernetes", "docker", "agentarea":
		if builtin == nil {
			return nil, "", fmt.Errorf("AGENTAREA_SBX_PROVIDER=%s requires an AgentArea sandbox backend", providerName)
		}
		return builtin, providerName, nil
	case "opensandbox", "e2b", "cube":
	default:
		return nil, "", fmt.Errorf("unsupported AGENTAREA_SBX_PROVIDER=%q; expected kubernetes, docker, opensandbox, e2b, or cube", providerName)
	}

	store, err := NewSessionStore(redisClient, os.Getenv("AGENTAREA_SBX_REDIS_PREFIX"), policy.SessionRecordTTL)
	if err != nil {
		return nil, "", err
	}
	manifest, err := loadExternalManifest()
	if err != nil {
		return nil, "", err
	}
	allowInternet, err := requiredBoolEnv("AGENTAREA_SBX_ALLOW_INTERNET")
	if err != nil {
		return nil, "", err
	}

	var provider ExternalProvider
	switch providerName {
	case "opensandbox":
		allowInsecure, err := strictBoolEnv("AGENTAREA_SBX_OSB_INSECURE", false)
		if err != nil {
			return nil, "", err
		}
		allowWeakDev, err := strictBoolEnv("AGENTAREA_SBX_OSB_WEAK_ISOLATION", false)
		if err != nil {
			return nil, "", err
		}
		apiKey := os.Getenv("AGENTAREA_SBX_OSB_API_KEY")
		if apiKey == "" && !allowInsecure {
			return nil, "", fmt.Errorf("AGENTAREA_SBX_OSB_API_KEY is required unless AGENTAREA_SBX_OSB_INSECURE=true")
		}
		useProxy, err := strictBoolEnv("AGENTAREA_SBX_OSB_SERVER_PROXY", true)
		if err != nil {
			return nil, "", err
		}
		secureAccess, err := strictBoolEnv("AGENTAREA_SBX_OSB_SECURE_ACCESS", true)
		if err != nil {
			return nil, "", err
		}
		entrypoint, err := stringSliceJSONEnv("AGENTAREA_SBX_OSB_ENTRYPOINT")
		if err != nil {
			return nil, "", err
		}
		retryConfig := opensandbox.DefaultRetryConfig()
		provider, err = NewOpenSandboxProvider(OpenSandboxConfig{
			Connection: opensandbox.ConnectionConfig{
				Domain:         os.Getenv("AGENTAREA_SBX_OSB_URL"),
				APIKey:         apiKey,
				AuthHeader:     getenv("AGENTAREA_SBX_OSB_AUTH_HEADER", "OPEN-SANDBOX-API-KEY"),
				UseServerProxy: useProxy,
				RequestTimeout: policy.ProviderProvisioningTimeout,
				Retry:          &retryConfig,
			},
			Image:               os.Getenv("AGENTAREA_SBX_OSB_IMAGE"),
			Entrypoint:          entrypoint,
			ResourceCPU:         getenv("AGENTAREA_SBX_CPU", "500m"),
			ResourceMemory:      getenv("AGENTAREA_SBX_MEMORY", "512Mi"),
			ResourceStorage:     strconv.FormatInt(workspaceLimits.MaxBytes, 10),
			LeaseTTL:            policy.TaskLeaseTTL,
			Isolation:           os.Getenv("AGENTAREA_SBX_OSB_ISOLATION"),
			RuntimeIdentity:     os.Getenv("AGENTAREA_SBX_OSB_IDENTITY"),
			AllowWeakDev:        allowWeakDev,
			AllowInsecure:       allowInsecure,
			SecureAccess:        &secureAccess,
			EgressMode:          os.Getenv("AGENTAREA_SBX_OSB_EGRESS"),
			AllowInternetAccess: allowInternet,
		})
		if err != nil {
			return nil, "", err
		}
	case "e2b", "cube":
		prefix := "AGENTAREA_SBX_" + strings.ToUpper(providerName) + "_"
		allowInsecure, err := strictBoolEnv(prefix+"INSECURE", false)
		if err != nil {
			return nil, "", err
		}
		provider, err = NewE2BProvider(E2BConfig{
			ProviderName:        providerName,
			APIURL:              os.Getenv(prefix + "URL"),
			APIKey:              os.Getenv(prefix + "API_KEY"),
			SandboxURL:          os.Getenv(prefix + "SANDBOX_URL"),
			Template:            os.Getenv(prefix + "TEMPLATE"),
			LeaseTTL:            policy.TaskLeaseTTL,
			RequestTimeout:      policy.ProviderProvisioningTimeout,
			AllowInternetAccess: allowInternet,
			AllowInsecure:       allowInsecure,
			Isolation:           os.Getenv(prefix + "ISOLATION"),
			RuntimeIdentity:     os.Getenv(prefix + "IDENTITY"),
			AttestationPath:     getenv(prefix+"ATTESTATION", DefaultIsolationAttestationPath),
		})
		if err != nil {
			return nil, "", err
		}
	}

	manager, err := NewManager(provider, store, policy.TaskLeaseTTL, policy.TaskIdleTTL, manifest, workspaceLimits)
	if err != nil {
		return nil, "", err
	}
	if lister, ok := provider.(ExternalSandboxLister); ok {
		return &managerWithInventory{Manager: manager, lister: lister}, providerName, nil
	}
	return manager, providerName, nil
}

func loadExternalManifest() (*runtimeinfo.Manifest, error) {
	manifestPath := os.Getenv("AGENTAREA_SBX_MANIFEST_PATH")
	manifestJSON := os.Getenv("AGENTAREA_SBX_MANIFEST_JSON")
	if manifestPath != "" && manifestJSON != "" {
		return nil, fmt.Errorf("AGENTAREA_SBX_MANIFEST_PATH and AGENTAREA_SBX_MANIFEST_JSON are mutually exclusive")
	}
	if manifestPath == "" && manifestJSON == "" {
		return nil, fmt.Errorf("external sandbox provider requires AGENTAREA_SBX_MANIFEST_PATH or AGENTAREA_SBX_MANIFEST_JSON")
	}
	var manifest *runtimeinfo.Manifest
	var err error
	if manifestPath != "" {
		manifest, err = runtimeinfo.Load(manifestPath)
	} else {
		manifest, err = decodeManifestJSON(manifestJSON)
	}
	if err != nil {
		return nil, fmt.Errorf("sandbox runtime manifest: %w", err)
	}
	return manifest, nil
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

func requiredDurationEnv(name string) (time.Duration, error) {
	value := os.Getenv(name)
	if value == "" {
		return 0, fmt.Errorf("%s is required", name)
	}
	duration, err := time.ParseDuration(value)
	if err != nil || duration <= 0 {
		return 0, fmt.Errorf("%s must be a positive duration", name)
	}
	return duration, nil
}

func requiredNonNegativeDurationEnv(name string) (time.Duration, error) {
	value := os.Getenv(name)
	if value == "" {
		return 0, fmt.Errorf("%s is required", name)
	}
	duration, err := time.ParseDuration(value)
	if err != nil || duration < 0 {
		return 0, fmt.Errorf("%s must be a non-negative duration", name)
	}
	return duration, nil
}

func strictBoolEnv(name string, fallback bool) (bool, error) {
	value := os.Getenv(name)
	if value == "" {
		return fallback, nil
	}
	parsed, err := strconv.ParseBool(value)
	if err != nil {
		return false, fmt.Errorf("%s must be true or false", name)
	}
	return parsed, nil
}

func requiredBoolEnv(name string) (bool, error) {
	value := os.Getenv(name)
	if value == "" {
		return false, fmt.Errorf("%s is required", name)
	}
	parsed, err := strconv.ParseBool(value)
	if err != nil {
		return false, fmt.Errorf("%s must be true or false", name)
	}
	return parsed, nil
}

func stringSliceJSONEnv(name string) ([]string, error) {
	value := os.Getenv(name)
	if value == "" {
		return nil, nil
	}
	var result []string
	if err := json.Unmarshal([]byte(value), &result); err != nil {
		return nil, fmt.Errorf("%s must be a JSON string array: %w", name, err)
	}
	return result, nil
}

func getenv(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}
