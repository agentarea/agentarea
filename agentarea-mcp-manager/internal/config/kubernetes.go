package config

import (
	"fmt"
	"time"
)

// KubernetesConfig holds Kubernetes-specific configuration
type KubernetesConfig struct {
	// Basic settings
	Enabled   bool   `json:"enabled"`
	Namespace string `json:"namespace"`
	
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
	RunAsNonRoot             bool  `json:"run_as_non_root"`
	RunAsUser                int64 `json:"run_as_user"`
	ReadOnlyRootFilesystem   bool  `json:"read_only_root_filesystem"`
	AllowPrivilegeEscalation bool  `json:"allow_privilege_escalation"`
	DropCapabilities         []string `json:"drop_capabilities"`
}

// NetworkPolicyConfig defines network policy settings
type NetworkPolicyConfig struct {
	Enabled          bool     `json:"enabled"`
	AllowedNamespaces []string `json:"allowed_namespaces"`
	IngressRules     []NetworkPolicyRule `json:"ingress_rules"`
	EgressRules      []NetworkPolicyRule `json:"egress_rules"`
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
	Enabled           bool              `json:"enabled"`
	PrometheusEnabled bool              `json:"prometheus_enabled"`
	ServiceMonitor    ServiceMonitorConfig `json:"service_monitor"`
	Metrics           MetricsConfig     `json:"metrics"`
}

// ServiceMonitorConfig defines Prometheus ServiceMonitor settings
type ServiceMonitorConfig struct {
	Enabled   bool              `json:"enabled"`
	Labels    map[string]string `json:"labels,omitempty"`
	Interval  string            `json:"interval"`
	Path      string            `json:"path"`
	Port      string            `json:"port"`
}

// MetricsConfig defines metrics collection settings
type MetricsConfig struct {
	Path string `json:"path"`
	Port int    `json:"port"`
}

// TLSConfig defines TLS and certificate management settings
type TLSConfig struct {
	Enabled       bool   `json:"enabled"`
	SecretName    string `json:"secret_name"`
	CertManager   CertManagerConfig `json:"cert_manager"`
}

// CertManagerConfig defines cert-manager integration settings
type CertManagerConfig struct {
	Enabled     bool   `json:"enabled"`
	ClusterIssuer string `json:"cluster_issuer"`
	Issuer      string `json:"issuer,omitempty"`
}

// DefaultKubernetesConfig returns default Kubernetes configuration
func DefaultKubernetesConfig() KubernetesConfig {
	return KubernetesConfig{
		Enabled:   false,
		Namespace: "agentarea",
		Domain:    "mcp.local",
		IngressClass: "nginx",
		StorageClass: "standard",
		
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
			Enabled: true,
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

// GetInternalServiceURL generates the internal Kubernetes service URL
func (k *KubernetesConfig) GetInternalServiceURL(instanceName string, port int) string {
	return fmt.Sprintf("http://mcp-%s.%s.svc.cluster.local:%d", instanceName, k.Namespace, port)
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