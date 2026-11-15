// Package kube runs MCP workloads on Kubernetes: one ConfigMap, Secret,
// Deployment and Service per instance, each named mcp-{name}. Instances are
// reached only through the demand gateway, so no route or ingress is created.
package kube

import (
	"encoding/json"
	"errors"
	"fmt"
	"strconv"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/runtime/workload"
)

// Quantities is a CPU and memory pair in Kubernetes quantity syntax.
type Quantities struct {
	CPU    string
	Memory string
}

// SecurityContext is the operator's container security baseline; an isolation
// tier may only tighten it.
type SecurityContext struct {
	RunAsNonRoot             bool
	RunAsUser                int64
	ReadOnlyRootFilesystem   bool
	AllowPrivilegeEscalation bool
	DropCapabilities         []string
}

// InstancePod is operator customization merged onto every instance pod
// (AGENTAREA_K8S_INSTANCE_POD, the chart's Helm values as one JSON object).
// Platform labels and the security context are applied after it and win.
type InstancePod struct {
	Labels            map[string]string   `json:"labels,omitempty"`
	Annotations       map[string]string   `json:"annotations,omitempty"`
	NodeSelector      map[string]string   `json:"nodeSelector,omitempty"`
	Tolerations       []corev1.Toleration `json:"tolerations,omitempty"`
	Affinity          *corev1.Affinity    `json:"affinity,omitempty"`
	ImagePullSecrets  []string            `json:"imagePullSecrets,omitempty"`
	PriorityClassName string              `json:"priorityClassName,omitempty"`
	ScratchSizeLimit  string              `json:"scratchSizeLimit,omitempty"`
}

// Config is the Kubernetes backend's environment.
type Config struct {
	// Kubeconfig names the execution cluster when it is not the one this
	// process runs in. When set it wins, and failing to load it is fatal.
	Kubeconfig            string
	Namespace             string
	RuntimeClass          string
	PodServiceAccountName string
	ImagePullPolicy       string
	DefaultRequests       Quantities
	DefaultLimits         Quantities
	SecurityContext       SecurityContext
	InstancePod           InstancePod
	// DefaultIsolationTier confines an instance whose spec names no tier.
	DefaultIsolationTier string
}

const defaultScratchSizeLimit = "256Mi"

// LoadConfig reads the backend's variables; l reports what is malformed.
func LoadConfig(l *config.Loader) Config {
	cfg := Config{
		Kubeconfig:            l.StringEnv("KUBECONFIG", ""),
		Namespace:             l.StringEnv("AGENTAREA_K8S_NAMESPACE", "agentarea"),
		RuntimeClass:          l.StringEnv("AGENTAREA_K8S_RUNTIME_CLASS", ""),
		PodServiceAccountName: l.StringEnv("AGENTAREA_K8S_SERVICE_ACCOUNT", ""),
		ImagePullPolicy: l.OneOfEnv("AGENTAREA_K8S_PULL_POLICY", string(corev1.PullIfNotPresent),
			string(corev1.PullAlways), string(corev1.PullIfNotPresent), string(corev1.PullNever)),
		DefaultRequests: Quantities{
			CPU:    l.StringEnv("AGENTAREA_K8S_CPU_REQUEST", "100m"),
			Memory: l.StringEnv("AGENTAREA_K8S_MEMORY_REQUEST", "256Mi"),
		},
		DefaultLimits: Quantities{
			CPU:    l.StringEnv("AGENTAREA_K8S_CPU_LIMIT", "500m"),
			Memory: l.StringEnv("AGENTAREA_K8S_MEMORY_LIMIT", "512Mi"),
		},
		SecurityContext: SecurityContext{
			RunAsNonRoot:             l.BoolEnv("AGENTAREA_K8S_NON_ROOT", true),
			RunAsUser:                1000,
			ReadOnlyRootFilesystem:   l.BoolEnv("AGENTAREA_K8S_READONLY_ROOT", true),
			AllowPrivilegeEscalation: l.BoolEnv("AGENTAREA_K8S_PRIV_ESCALATION", false),
			DropCapabilities:         []string{"ALL"},
		},
		DefaultIsolationTier: l.StringEnv("AGENTAREA_MCP_ISOLATION", workload.IsolationUntrusted),
	}
	if v, ok := l.OptionalEnv("AGENTAREA_K8S_RUN_AS_USER"); ok {
		user, err := strconv.ParseInt(v, 10, 64)
		if err != nil {
			l.Fail("AGENTAREA_K8S_RUN_AS_USER", fmt.Errorf("must be an integer, got %q", v))
		}
		cfg.SecurityContext.RunAsUser = user
	}
	if v, ok := l.OptionalEnv("AGENTAREA_K8S_INSTANCE_POD"); ok {
		if err := json.Unmarshal([]byte(v), &cfg.InstancePod); err != nil {
			l.Fail("AGENTAREA_K8S_INSTANCE_POD", fmt.Errorf("must be valid JSON: %w", err))
		}
	}
	if _, err := cfg.scratchSizeLimit(); err != nil {
		l.Fail("AGENTAREA_K8S_INSTANCE_POD", err)
	}
	if _, err := workload.ResolveIsolation(cfg.DefaultIsolationTier); err != nil {
		l.Fail("AGENTAREA_MCP_ISOLATION", err)
	}
	for name, v := range map[string]string{
		"AGENTAREA_K8S_CPU_REQUEST":    cfg.DefaultRequests.CPU,
		"AGENTAREA_K8S_MEMORY_REQUEST": cfg.DefaultRequests.Memory,
		"AGENTAREA_K8S_CPU_LIMIT":      cfg.DefaultLimits.CPU,
		"AGENTAREA_K8S_MEMORY_LIMIT":   cfg.DefaultLimits.Memory,
	} {
		if err := positiveQuantity(v); err != nil {
			l.Fail(name, err)
		}
	}
	return cfg
}

func (c Config) validate() error {
	var errs []error
	if c.Namespace == "" {
		errs = append(errs, errors.New("kubernetes namespace is required"))
	}
	if _, err := c.scratchSizeLimit(); err != nil {
		errs = append(errs, err)
	}
	if _, err := workload.ResolveIsolation(c.DefaultIsolationTier); err != nil {
		errs = append(errs, fmt.Errorf("default isolation tier: %w", err))
	}
	for _, v := range []string{c.DefaultRequests.CPU, c.DefaultRequests.Memory, c.DefaultLimits.CPU, c.DefaultLimits.Memory} {
		if err := positiveQuantity(v); err != nil {
			errs = append(errs, err)
		}
	}
	return errors.Join(errs...)
}

func positiveQuantity(v string) error {
	if v == "" {
		return nil
	}
	q, err := resource.ParseQuantity(v)
	if err != nil {
		return fmt.Errorf("%q is not a quantity: %w", v, err)
	}
	if q.Sign() <= 0 {
		return fmt.Errorf("%q must be positive", v)
	}
	return nil
}

func (c Config) scratchSizeLimit() (resource.Quantity, error) {
	raw := c.InstancePod.ScratchSizeLimit
	if raw == "" {
		raw = defaultScratchSizeLimit
	}
	q, err := resource.ParseQuantity(raw)
	if err != nil {
		return resource.Quantity{}, fmt.Errorf("instance pod scratchSizeLimit %q is not a quantity: %w", raw, err)
	}
	if q.Sign() <= 0 {
		return resource.Quantity{}, fmt.Errorf("instance pod scratchSizeLimit must be positive, got %q", raw)
	}
	return q, nil
}

func (c Config) requests(spec workload.ResourceList) Quantities {
	return Quantities{CPU: or(spec.CPU, c.DefaultRequests.CPU), Memory: or(spec.Memory, c.DefaultRequests.Memory)}
}

func (c Config) limits(spec workload.ResourceList) Quantities {
	return Quantities{CPU: or(spec.CPU, c.DefaultLimits.CPU), Memory: or(spec.Memory, c.DefaultLimits.Memory)}
}

func or(v, def string) string {
	if v != "" {
		return v
	}
	return def
}
