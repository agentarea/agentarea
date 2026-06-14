package config

import (
	"fmt"
	"time"

	corev1 "k8s.io/api/core/v1"
)

// KubernetesConfig holds Kubernetes-specific configuration
type KubernetesConfig struct {
	// Basic settings
	Enabled   bool   `json:"enabled"`
	Namespace string `json:"namespace"`

	// Runtime configuration
	RuntimeClass string `json:"runtime_class"`

	// Service account to use for MCP server pods created by the Kubernetes backend.
	PodServiceAccountName string `json:"pod_service_account_name"`

	// Image pull policy (IfNotPresent, Always, Never). Defaults to IfNotPresent
	// which is safe for k3d/local dev; production clusters should set Always.
	ImagePullPolicy string `json:"image_pull_policy"`

	// Gateway API configuration
	GatewayName      string `json:"gateway_name"`
	GatewayNamespace string `json:"gateway_namespace"`

	// Networking
	Domain       string `json:"domain"`
	IngressClass string `json:"ingress_class"`

	// Storage
	StorageClass string `json:"storage_class"`

	// Resource defaults
	DefaultRequests ResourceRequirements `json:"default_requests"`
	DefaultLimits   ResourceRequirements `json:"default_limits"`

	// Security
	SecurityContext SecurityContextConfig `json:"security_context"`
	NetworkPolicy   NetworkPolicyConfig   `json:"network_policy"`

	// Operator-supplied customization applied to every spawned MCP instance pod.
	InstancePod InstancePodConfig `json:"instance_pod"`

	// Observability
	Monitoring MonitoringConfig `json:"monitoring"`

	// Timeouts
	DeploymentTimeout time.Duration `json:"deployment_timeout"`
	ReadinessTimeout  time.Duration `json:"readiness_timeout"`

	// TLS/Certificate management
	TLS TLSConfig `json:"tls"`
}

// ResourceRequirements defines Kubernetes resource requirements
type ResourceRequirements struct {
	CPU    string `json:"cpu,omitempty"`
	Memory string `json:"memory,omitempty"`
}

// SecurityContextConfig defines pod security context settings
type SecurityContextConfig struct {
	RunAsNonRoot             bool     `json:"run_as_non_root"`
	RunAsUser                int64    `json:"run_as_user"`
	ReadOnlyRootFilesystem   bool     `json:"read_only_root_filesystem"`
	AllowPrivilegeEscalation bool     `json:"allow_privilege_escalation"`
	DropCapabilities         []string `json:"drop_capabilities"`
}

// NetworkPolicyConfig defines network policy settings
type NetworkPolicyConfig struct {
	Enabled           bool                `json:"enabled"`
	AllowedNamespaces []string            `json:"allowed_namespaces"`
	IngressRules      []NetworkPolicyRule `json:"ingress_rules"`
	EgressRules       []NetworkPolicyRule `json:"egress_rules"`
}

// InstancePodConfig is operator-supplied customization merged onto every spawned
// MCP instance pod. All fields are optional (empty = no change). Platform
// security invariants (managed-by label, securityContext, seccomp, the SA-token
// withholding, runtime-class clamp) are applied AFTER these and always win, so
// nothing here can weaken instance isolation. The JSON tags are camelCase to
// match the Helm values keys verbatim (the chart passes this struct as a single
// JSON-encoded env var, KUBERNETES_INSTANCE_POD).
type InstancePodConfig struct {
	Labels            map[string]string   `json:"labels,omitempty"`
	Annotations       map[string]string   `json:"annotations,omitempty"`
	NodeSelector      map[string]string   `json:"nodeSelector,omitempty"`
	Tolerations       []corev1.Toleration `json:"tolerations,omitempty"`
	Affinity          *corev1.Affinity    `json:"affinity,omitempty"`
	ImagePullSecrets  []string            `json:"imagePullSecrets,omitempty"`
	PriorityClassName string              `json:"priorityClassName,omitempty"`
}

// NetworkPolicyRule defines a network policy rule
type NetworkPolicyRule struct {
	From  []NetworkPolicyPeer `json:"from,omitempty"`
	To    []NetworkPolicyPeer `json:"to,omitempty"`
	Ports []NetworkPolicyPort `json:"ports,omitempty"`
}

// NetworkPolicyPeer defines a network policy peer
type NetworkPolicyPeer struct {
	NamespaceSelector map[string]string `json:"namespace_selector,omitempty"`
	PodSelector       map[string]string `json:"pod_selector,omitempty"`
}

// NetworkPolicyPort defines a network policy port
type NetworkPolicyPort struct {
	Protocol string `json:"protocol,omitempty"`
	Port     int    `json:"port,omitempty"`
}

// MonitoringConfig defines monitoring and observability settings
type MonitoringConfig struct {
	Enabled           bool                 `json:"enabled"`
	PrometheusEnabled bool                 `json:"prometheus_enabled"`
	ServiceMonitor    ServiceMonitorConfig `json:"service_monitor"`
	Metrics           MetricsConfig        `json:"metrics"`
}

// ServiceMonitorConfig defines Prometheus ServiceMonitor settings
type ServiceMonitorConfig struct {
	Enabled  bool              `json:"enabled"`
	Labels   map[string]string `json:"labels,omitempty"`
	Interval string            `json:"interval"`
	Path     string            `json:"path"`
	Port     string            `json:"port"`
}

// MetricsConfig defines metrics collection settings
type MetricsConfig struct {
	Path string `json:"path"`
	Port int    `json:"port"`
}

// TLSConfig defines TLS and certificate management settings
type TLSConfig struct {
	Enabled     bool              `json:"enabled"`
	SecretName  string            `json:"secret_name"`
	CertManager CertManagerConfig `json:"cert_manager"`
}

// CertManagerConfig defines cert-manager integration settings
type CertManagerConfig struct {
	Enabled       bool   `json:"enabled"`
	ClusterIssuer string `json:"cluster_issuer"`
	Issuer        string `json:"issuer,omitempty"`
}

// DefaultKubernetesConfig returns default Kubernetes configuration
func DefaultKubernetesConfig() KubernetesConfig {
	return KubernetesConfig{
		Enabled:               false,
		Namespace:             "agentarea",
		Domain:                "mcp.local",
		IngressClass:          "nginx",
		StorageClass:          "standard",
		ImagePullPolicy:       "IfNotPresent",
		PodServiceAccountName: "",

		DefaultRequests: ResourceRequirements{
			CPU:    "100m",
			Memory: "256Mi",
		},
		DefaultLimits: ResourceRequirements{
			CPU:    "500m",
			Memory: "512Mi",
		},

		SecurityContext: SecurityContextConfig{
			RunAsNonRoot:             true,
			RunAsUser:                1000,
			ReadOnlyRootFilesystem:   true,
			AllowPrivilegeEscalation: false,
			DropCapabilities:         []string{"ALL"},
		},

		NetworkPolicy: NetworkPolicyConfig{
			Enabled:           true,
			AllowedNamespaces: []string{"ingress-nginx", "kube-system"},
			IngressRules: []NetworkPolicyRule{
				{
					From: []NetworkPolicyPeer{
						{
							NamespaceSelector: map[string]string{
								"name": "ingress-nginx",
							},
						},
					},
					Ports: []NetworkPolicyPort{
						{Protocol: "TCP", Port: 8000},
					},
				},
			},
		},

		Monitoring: MonitoringConfig{
			Enabled:           true,
			PrometheusEnabled: true,
			ServiceMonitor: ServiceMonitorConfig{
				Enabled:  true,
				Interval: "30s",
				Path:     "/metrics",
				Port:     "metrics",
			},
			Metrics: MetricsConfig{
				Path: "/metrics",
				Port: 9090,
			},
		},

		DeploymentTimeout: 300 * time.Second,
		ReadinessTimeout:  120 * time.Second,

		TLS: TLSConfig{
			Enabled:    true,
			SecretName: "mcp-tls",
			CertManager: CertManagerConfig{
				Enabled:       true,
				ClusterIssuer: "letsencrypt-prod",
			},
		},
	}
}

// Validate validates the Kubernetes configuration
func (k *KubernetesConfig) Validate() error {
	if k.Enabled {
		if k.Namespace == "" {
			return fmt.Errorf("kubernetes namespace is required when kubernetes is enabled")
		}
		if k.Domain == "" {
			return fmt.Errorf("kubernetes domain is required when kubernetes is enabled")
		}
		if k.IngressClass == "" {
			return fmt.Errorf("kubernetes ingress class is required when kubernetes is enabled")
		}
	}
	return nil
}

// GetResourceRequirements returns resource requirements with defaults applied
func (k *KubernetesConfig) GetResourceRequirements(requests, limits *ResourceRequirements) ResourceRequirements {
	result := ResourceRequirements{}

	// Apply requests
	if requests != nil && requests.CPU != "" {
		result.CPU = requests.CPU
	} else {
		result.CPU = k.DefaultRequests.CPU
	}

	if requests != nil && requests.Memory != "" {
		result.Memory = requests.Memory
	} else {
		result.Memory = k.DefaultRequests.Memory
	}

	return result
}

// GetResourceLimits returns resource limits with defaults applied
func (k *KubernetesConfig) GetResourceLimits(limits *ResourceRequirements) ResourceRequirements {
	result := ResourceRequirements{}

	if limits != nil && limits.CPU != "" {
		result.CPU = limits.CPU
	} else {
		result.CPU = k.DefaultLimits.CPU
	}

	if limits != nil && limits.Memory != "" {
		result.Memory = limits.Memory
	} else {
		result.Memory = k.DefaultLimits.Memory
	}

	return result
}

// GetInstanceURL generates the external URL for an MCP instance
func (k *KubernetesConfig) GetInstanceURL(instanceName string) string {
	protocol := "http"
	if k.TLS.Enabled {
		protocol = "https"
	}
	return fmt.Sprintf("%s://%s/mcp/%s", protocol, k.Domain, instanceName)
}

// GetInternalServiceURL generates the internal Kubernetes service URL.
//
// The backend-created Service always exposes port 80 → TargetPort spec.Port,
// so callers must reach the Service on 80 (the provided port arg is the
// container's internal port and is ignored for URL construction — kept in the
// signature for API compatibility).
func (k *KubernetesConfig) GetInternalServiceURL(instanceName string, port int) string {
	_ = port
	return fmt.Sprintf("http://mcp-%s.%s.svc.cluster.local:80", instanceName, k.Namespace)
}

// GetIngressAnnotations returns ingress annotations based on configuration
func (k *KubernetesConfig) GetIngressAnnotations() map[string]string {
	annotations := map[string]string{
		"nginx.ingress.kubernetes.io/rewrite-target": "/$2",
	}

	if k.TLS.Enabled && k.TLS.CertManager.Enabled {
		if k.TLS.CertManager.ClusterIssuer != "" {
			annotations["cert-manager.io/cluster-issuer"] = k.TLS.CertManager.ClusterIssuer
		} else if k.TLS.CertManager.Issuer != "" {
			annotations["cert-manager.io/issuer"] = k.TLS.CertManager.Issuer
		}
	}

	return annotations
}
