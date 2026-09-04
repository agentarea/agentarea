// Package features provides feature flagging capabilities.
// Currently config-based, can be swapped for remote feature service later.
package features

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"strings"
)

// Feature represents a feature flag
type Feature string

const (
	// WarmPool enables warm pool for fast MCP activation
	WarmPool Feature = "warm_pool"

	// KataRuntime enables Kata Containers for VM isolation
	KataRuntime Feature = "kata_runtime"

	// AdvancedScaling enables KEDA/enterprise scaling options
	AdvancedScaling Feature = "advanced_scaling"

	// StateReconciler enables background state reconciliation
	StateReconciler Feature = "state_reconciler"

	// GatewayAPI enables HTTPRoute creation for Envoy Gateway
	GatewayAPI Feature = "gateway_api"
)

// AllFeatures lists all available features
var AllFeatures = []Feature{
	WarmPool,
	KataRuntime,
	AdvancedScaling,
	StateReconciler,
	GatewayAPI,
}

// Provider defines the interface for feature flag resolution
// This can be implemented by:
// - ConfigProvider (static config)
// - EnvironmentProvider (env vars)
// - RemoteProvider (feature service API)
// - HybridProvider (cascading resolution)
type Provider interface {
	// IsEnabled returns true if the feature is enabled
	IsEnabled(ctx context.Context, feature Feature) bool

	// GetVariant returns variant config for a feature (e.g., warm pool size)
	GetVariant(ctx context.Context, feature Feature) map[string]string

	// Reload reloads feature configuration (for remote providers)
	Reload(ctx context.Context) error
}

// Config-based provider (current implementation)
type ConfigProvider struct {
	logger   *slog.Logger
	features map[Feature]bool
	variants map[Feature]map[string]string
}

// Config for feature flags
type Config struct {
	// Simple on/off flags
	Enabled []string `json:"enabled" yaml:"enabled"`

	// Feature variants (e.g., warm pool size)
	Variants map[string]map[string]string `json:"variants" yaml:"variants"`
}

// NewConfigProvider creates a provider from static config
func NewConfigProvider(logger *slog.Logger, cfg *Config) *ConfigProvider {
	p := &ConfigProvider{
		logger:   logger.With("component", "features"),
		features: make(map[Feature]bool),
		variants: make(map[Feature]map[string]string),
	}

	// Parse enabled features
	for _, f := range cfg.Enabled {
		feature := Feature(strings.ToLower(f))
		p.features[feature] = true
		p.logger.Info("Feature enabled", "feature", feature)
	}

	// Parse variants
	for name, variant := range cfg.Variants {
		feature := Feature(strings.ToLower(name))
		p.variants[feature] = variant
	}

	return p
}

// IsEnabled checks if feature is enabled in config
func (p *ConfigProvider) IsEnabled(ctx context.Context, feature Feature) bool {
	enabled := p.features[feature]
	p.logger.Debug("Feature check",
		"feature", feature,
		"enabled", enabled,
	)
	return enabled
}

// GetVariant returns variant config for a feature
func (p *ConfigProvider) GetVariant(ctx context.Context, feature Feature) map[string]string {
	if variant, ok := p.variants[feature]; ok {
		return variant
	}
	return make(map[string]string)
}

// Reload is no-op for config provider
func (p *ConfigProvider) Reload(ctx context.Context) error {
	return nil
}

// Environment-based provider (reads from env vars)
type EnvironmentProvider struct {
	prefix string
	logger *slog.Logger
}

// NewEnvironmentProvider creates provider that reads from env vars
// e.g., MCP_FEATURE_WARM_POOL=true
func NewEnvironmentProvider(logger *slog.Logger, prefix string) *EnvironmentProvider {
	if prefix == "" {
		prefix = "MCP_FEATURE"
	}
	return &EnvironmentProvider{
		prefix: prefix,
		logger: logger.With("component", "features", "source", "env"),
	}
}

// IsEnabled checks env var like MCP_FEATURE_WARM_POOL
func (p *EnvironmentProvider) IsEnabled(ctx context.Context, feature Feature) bool {
	envVar := fmt.Sprintf("%s_%s", p.prefix, strings.ToUpper(string(feature)))
	envVar = strings.ReplaceAll(envVar, ".", "_")

	value := os.Getenv(envVar)
	enabled := value == "true" || value == "1" || value == "yes"

	p.logger.Debug("Feature check from env",
		"feature", feature,
		"env_var", envVar,
		"enabled", enabled,
	)

	return enabled
}

// GetVariant returns empty for env provider (no complex config)
func (p *EnvironmentProvider) GetVariant(ctx context.Context, feature Feature) map[string]string {
	return make(map[string]string)
}

// Reload is no-op for env provider
func (p *EnvironmentProvider) Reload(ctx context.Context) error {
	return nil
}

// Hybrid provider checks multiple sources in order
type HybridProvider struct {
	providers []Provider
	logger    *slog.Logger
}

// NewHybridProvider creates provider that checks multiple sources
// First provider that returns true wins
func NewHybridProvider(logger *slog.Logger, providers ...Provider) *HybridProvider {
	return &HybridProvider{
		providers: providers,
		logger:    logger.With("component", "features", "source", "hybrid"),
	}
}

// IsEnabled checks all providers in order
func (p *HybridProvider) IsEnabled(ctx context.Context, feature Feature) bool {
	for _, provider := range p.providers {
		if provider.IsEnabled(ctx, feature) {
			return true
		}
	}
	return false
}

// GetVariant returns from first provider that has variant
func (p *HybridProvider) GetVariant(ctx context.Context, feature Feature) map[string]string {
	for _, provider := range p.providers {
		variant := provider.GetVariant(ctx, feature)
		if len(variant) > 0 {
			return variant
		}
	}
	return make(map[string]string)
}

// Reload reloads all providers
func (p *HybridProvider) Reload(ctx context.Context) error {
	for _, provider := range p.providers {
		if err := provider.Reload(ctx); err != nil {
			return err
		}
	}
	return nil
}

// Service is the main feature flag service used by application
type Service struct {
	provider Provider
	logger   *slog.Logger
}

// NewService creates a new feature service
func NewService(logger *slog.Logger, provider Provider) *Service {
	return &Service{
		provider: provider,
		logger:   logger.With("component", "features"),
	}
}

// IsEnabled checks if a feature is enabled
func (s *Service) IsEnabled(feature Feature) bool {
	return s.provider.IsEnabled(context.Background(), feature)
}

// IsEnabledCtx checks if a feature is enabled with context
func (s *Service) IsEnabledCtx(ctx context.Context, feature Feature) bool {
	return s.provider.IsEnabled(ctx, feature)
}

// GetVariant gets variant config for a feature
func (s *Service) GetVariant(feature Feature) map[string]string {
	return s.provider.GetVariant(context.Background(), feature)
}

// GetVariantCtx gets variant config with context
func (s *Service) GetVariantCtx(ctx context.Context, feature Feature) map[string]string {
	return s.provider.GetVariant(ctx, feature)
}

// Check helpers for specific features
func (s *Service) KataRuntimeEnabled() bool {
	return s.IsEnabled(KataRuntime)
}

func (s *Service) AdvancedScalingEnabled() bool {
	return s.IsEnabled(AdvancedScaling)
}

func (s *Service) StateReconcilerEnabled() bool {
	return s.IsEnabled(StateReconciler)
}

func (s *Service) GatewayAPIEnabled() bool {
	return s.IsEnabled(GatewayAPI)
}

// GetWarmPoolConfig and its WarmPoolConfig struct were removed here. They had no
// callers: nothing read Size, and nothing read IdleTimeout — the pool size comes
// from the chart, and MCP instance idleness is owned by internal/mcpgateway via
// request leases and MCP_IDLE_TIMEOUT. Keeping them was worse than dead weight, because an
// `idle_timeout` variant on the warm_pool flag reads as the way to configure
// exactly the thing it did not configure. Restore from git history if a warm
// pool ever needs per-variant tuning.

// Reload reloads feature configuration
func (s *Service) Reload() error {
	return s.provider.Reload(context.Background())
}

// SetProvider allows swapping provider at runtime (for testing)
func (s *Service) SetProvider(provider Provider) {
	s.provider = provider
}

// DefaultService is the global feature service (set during init)
var DefaultService *Service

// InitDefaultService initializes the global service
func InitDefaultService(logger *slog.Logger, provider Provider) {
	DefaultService = NewService(logger, provider)
}

// Helper functions using default service
func IsEnabled(feature Feature) bool {
	if DefaultService == nil {
		return false
	}
	return DefaultService.IsEnabled(feature)
}

func WarmPoolEnabled() bool {
	return IsEnabled(WarmPool)
}

func KataRuntimeEnabled() bool {
	return IsEnabled(KataRuntime)
}

func AdvancedScalingEnabled() bool {
	return IsEnabled(AdvancedScaling)
}

// Example usage in code:
//
// if features.IsEnabled(features.WarmPool) {
//     return b.createWithWarmPool(ctx, instance)
// }
// return b.createStandard(ctx, instance)
