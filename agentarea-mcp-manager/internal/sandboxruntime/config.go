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
func NewFromEnv(_ context.Context, legacy Runtime, redisClient *redis.Client, defaultProvider string) (Runtime, string, error) {
	providerName := strings.ToLower(strings.TrimSpace(os.Getenv("SANDBOX_PROVIDER")))
	if providerName == "" {
		providerName = defaultProvider
	}
	switch providerName {
	case "kubernetes", "docker", "agentarea":
		if legacy == nil {
			return nil, "", fmt.Errorf("SANDBOX_PROVIDER=%s requires an AgentArea sandbox backend", providerName)
		}
		return legacy, providerName, nil
	case "opensandbox", "e2b", "cube":
	default:
		return nil, "", fmt.Errorf("unsupported SANDBOX_PROVIDER=%q; expected kubernetes, docker, opensandbox, e2b, or cube", providerName)
	}

	leaseTTL, err := strictDurationEnv("SANDBOX_TASK_LEASE_TTL", 2*time.Hour)
	if err != nil {
		return nil, "", err
	}
	if _, err := strictNonNegativeDurationEnv("SANDBOX_TASK_IDLE_TTL", 15*time.Minute); err != nil {
		return nil, "", err
	}
	sessionTTL, err := strictDurationEnv("SANDBOX_PROVIDER_SESSION_TTL", 24*time.Hour)
	if err != nil {
		return nil, "", err
	}
	if sessionTTL <= leaseTTL {
		return nil, "", fmt.Errorf("SANDBOX_PROVIDER_SESSION_TTL must be greater than SANDBOX_TASK_LEASE_TTL")
	}
	store, err := NewSessionStore(redisClient, os.Getenv("SANDBOX_CONTROL_REDIS_PREFIX"), sessionTTL)
	if err != nil {
		return nil, "", err
	}
	manifests, err := loadExternalManifests()
	if err != nil {
		return nil, "", err
	}

	var provider ExternalProvider
	switch providerName {
	case "opensandbox":
		allowInsecure, err := strictBoolEnv("SANDBOX_OPENSANDBOX_ALLOW_INSECURE", false)
		if err != nil {
			return nil, "", err
		}
		allowWeakDev, err := strictBoolEnv("SANDBOX_OPENSANDBOX_ALLOW_WEAK_ISOLATION_FOR_DEVELOPMENT", false)
		if err != nil {
			return nil, "", err
		}
		apiKey := os.Getenv("SANDBOX_OPENSANDBOX_API_KEY")
		if apiKey == "" && !allowInsecure {
			return nil, "", fmt.Errorf("SANDBOX_OPENSANDBOX_API_KEY is required unless SANDBOX_OPENSANDBOX_ALLOW_INSECURE=true")
		}
		useProxy, err := strictBoolEnv("SANDBOX_OPENSANDBOX_USE_SERVER_PROXY", true)
		if err != nil {
			return nil, "", err
		}
		secureAccess, err := strictBoolEnv("SANDBOX_OPENSANDBOX_SECURE_ACCESS", true)
		if err != nil {
			return nil, "", err
		}
		entrypoint, err := stringSliceJSONEnv("SANDBOX_OPENSANDBOX_ENTRYPOINT")
		if err != nil {
			return nil, "", err
		}
		retryConfig := opensandbox.DefaultRetryConfig()
		persistWorkspace, err := strictBoolEnv("SANDBOX_OPENSANDBOX_PERSIST_WORKSPACE", true)
		if err != nil {
			return nil, "", err
		}
		provider, err = NewOpenSandboxProvider(OpenSandboxConfig{
			Connection: opensandbox.ConnectionConfig{
				Domain:         os.Getenv("SANDBOX_OPENSANDBOX_URL"),
				APIKey:         apiKey,
				AuthHeader:     getenv("SANDBOX_OPENSANDBOX_AUTH_HEADER", "OPEN-SANDBOX-API-KEY"),
				UseServerProxy: useProxy,
				RequestTimeout: 30 * time.Second,
				Retry:          &retryConfig,
			},
			Images: map[string]string{
				runtimeinfo.PackageInstallAllowed: os.Getenv("SANDBOX_OPENSANDBOX_IMAGE_ALLOWED"),
				runtimeinfo.PackageInstallLocked:  os.Getenv("SANDBOX_OPENSANDBOX_IMAGE_LOCKED"),
			},
			Entrypoint:       entrypoint,
			ResourceCPU:      getenv("SANDBOX_PROVIDER_CPU", "500m"),
			ResourceMemory:   getenv("SANDBOX_PROVIDER_MEMORY", "512Mi"),
			LeaseTTL:         leaseTTL,
			Isolation:        os.Getenv("SANDBOX_OPENSANDBOX_ISOLATION"),
			AllowWeakDev:     allowWeakDev,
			AllowInsecure:    allowInsecure,
			SecureAccess:     &secureAccess,
			EgressMode:       os.Getenv("SANDBOX_OPENSANDBOX_EGRESS_MODE"),
			PersistWorkspace: persistWorkspace,
			VolumePrefix:     getenv("SANDBOX_OPENSANDBOX_VOLUME_PREFIX", "agentarea-task"),
		})
		if err != nil {
			return nil, "", err
		}
	case "e2b", "cube":
		prefix := "SANDBOX_" + strings.ToUpper(providerName) + "_"
		allowInternetAllowed, err := strictBoolEnv(prefix+"ALLOW_INTERNET_ALLOWED", false)
		if err != nil {
			return nil, "", err
		}
		allowInternetLocked, err := strictBoolEnv(prefix+"ALLOW_INTERNET_LOCKED", false)
		if err != nil {
			return nil, "", err
		}
		allowInsecure, err := strictBoolEnv(prefix+"ALLOW_INSECURE", false)
		if err != nil {
			return nil, "", err
		}
		provider, err = NewE2BProvider(E2BConfig{
			ProviderName: providerName,
			APIURL:       os.Getenv(prefix + "API_URL"),
			APIKey:       os.Getenv(prefix + "API_KEY"),
			SandboxURL:   os.Getenv(prefix + "SANDBOX_URL"),
			Templates: map[string]string{
				runtimeinfo.PackageInstallAllowed: os.Getenv(prefix + "TEMPLATE_ALLOWED"),
				runtimeinfo.PackageInstallLocked:  os.Getenv(prefix + "TEMPLATE_LOCKED"),
			},
			LeaseTTL:       leaseTTL,
			RequestTimeout: 30 * time.Second,
			InternetAccess: map[string]bool{
				runtimeinfo.PackageInstallAllowed: allowInternetAllowed,
				runtimeinfo.PackageInstallLocked:  allowInternetLocked,
			},
			AllowInsecure: allowInsecure,
		})
		if err != nil {
			return nil, "", err
		}
	}

	manager, err := NewManager(provider, store, leaseTTL, manifests)
	if err != nil {
		return nil, "", err
	}
	return manager, providerName, nil
}

func loadExternalManifests() (map[string]*runtimeinfo.Manifest, error) {
	result := make(map[string]*runtimeinfo.Manifest, 2)
	for _, profile := range []string{runtimeinfo.PackageInstallAllowed, runtimeinfo.PackageInstallLocked} {
		prefix := "SANDBOX_RUNTIME_MANIFEST_" + strings.ToUpper(profile)
		manifestPath := os.Getenv(prefix + "_PATH")
		manifestJSON := os.Getenv(prefix + "_JSON")
		if manifestPath != "" && manifestJSON != "" {
			return nil, fmt.Errorf("%s_PATH and %s_JSON are mutually exclusive", prefix, prefix)
		}
		if manifestPath == "" && manifestJSON == "" {
			continue
		}
		var manifest *runtimeinfo.Manifest
		var err error
		if manifestPath != "" {
			manifest, err = runtimeinfo.Load(manifestPath)
		} else {
			manifest, err = decodeManifestJSON(manifestJSON)
		}
		if err != nil {
			return nil, fmt.Errorf("%s: %w", prefix, err)
		}
		if !manifest.SupportsPackageInstall(profile) {
			return nil, fmt.Errorf("%s does not enforce package_install=%s", prefix, profile)
		}
		result[profile] = manifest
	}
	if len(result) == 0 {
		return nil, fmt.Errorf("external sandbox provider requires at least one SANDBOX_RUNTIME_MANIFEST_{ALLOWED,LOCKED}_{PATH,JSON}")
	}
	return result, nil
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

func strictDurationEnv(name string, fallback time.Duration) (time.Duration, error) {
	value := os.Getenv(name)
	if value == "" {
		return fallback, nil
	}
	duration, err := time.ParseDuration(value)
	if err != nil || duration <= 0 {
		return 0, fmt.Errorf("%s must be a positive duration", name)
	}
	return duration, nil
}

func strictNonNegativeDurationEnv(name string, fallback time.Duration) (time.Duration, error) {
	value := os.Getenv(name)
	if value == "" {
		return fallback, nil
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
