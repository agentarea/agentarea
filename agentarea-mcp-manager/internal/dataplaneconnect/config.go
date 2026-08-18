package dataplaneconnect

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
)

type Config struct {
	ControlPlaneURL string `json:"control_plane_url"`
	// ConnectorGatewayURL is the optional outbound ConnectRPC endpoint. It is
	// deliberately distinct from ControlPlaneURL: the latter keeps enrollment
	// and legacy heartbeats working while the former carries commands.
	ConnectorGatewayURL      string              `json:"connector_gateway_url,omitempty"`
	DataPlaneID              DataPlaneID         `json:"data_plane_id"`
	ConnectorInstanceID      ConnectorInstanceID `json:"connector_instance_id"`
	IdentityFile             string              `json:"identity_file"`
	EnrollmentTokenFile      string              `json:"enrollment_token_file"`
	AllowInsecureDevelopment bool                `json:"allow_insecure_development"`
	HTTPTimeout              time.Duration       `json:"-"`
	HeartbeatInterval        time.Duration       `json:"-"`
	HTTPTimeoutString        string              `json:"http_timeout,omitempty"`
	HeartbeatIntervalString  string              `json:"heartbeat_interval,omitempty"`
	Capabilities             Capabilities        `json:"capabilities"`
	// Providers are explicit opt-ins. A connector never installs a provider;
	// it only binds to an already available provider selected here.
	MCPProvider               string        `json:"mcp_provider,omitempty"`
	SandboxProvider           string        `json:"sandbox_provider,omitempty"`
	KubernetesNamespace       string        `json:"kubernetes_namespace,omitempty"`
	KubernetesKubeconfig      string        `json:"kubernetes_kubeconfig,omitempty"`
	DockerRuntime             string        `json:"docker_runtime,omitempty"`
	DockerNetwork             string        `json:"docker_network,omitempty"`
	DockerNamePrefix          string        `json:"docker_name_prefix,omitempty"`
	DockerMaxContainers       int           `json:"docker_max_containers,omitempty"`
	SandboxTaskLeaseTTL       time.Duration `json:"-"`
	SandboxTaskLeaseTTLString string        `json:"sandbox_task_lease_ttl,omitempty"`
	SandboxStateRedisURL      string        `json:"sandbox_state_redis_url,omitempty"`
	AgentVersion              string        `json:"agent_version,omitempty"`
}

// BuildVersion is set by the release build. It is kept in this package so the
// outbound heartbeat reports the exact binary version that is running.
var BuildVersion = "dev"

func DefaultConfig() Config {
	return Config{
		IdentityFile:      "/var/lib/agentarea-data-plane-agent/identity.json",
		HTTPTimeout:       10 * time.Second,
		HeartbeatInterval: 30 * time.Second,
		// Capabilities are discovered from constructed adapters. Configuration
		// hints must never cause an unconfigured runtime to be advertised.
		Capabilities:        Capabilities{},
		MCPProvider:         "disabled",
		SandboxProvider:     "disabled",
		SandboxTaskLeaseTTL: 15 * time.Minute,
		DockerRuntime:       "docker",
		DockerNetwork:       "bridge",
		DockerNamePrefix:    "agentarea-mcp-",
		DockerMaxContainers: 50,
		AgentVersion:        BuildVersion,
	}
}

// LoadConfig accepts a strict JSON config and environment/flag overrides. The
// precedence is flags, environment, then JSON file.
func LoadConfig(args []string) (Config, error) {
	fs := flag.NewFlagSet("data-plane-agent", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	configPath := fs.String("config", "", "JSON config file")
	urlFlag := fs.String("control-plane-url", "", "control plane URL")
	connectorGatewayFlag := fs.String("connector-gateway-url", "", "outbound connector gateway URL")
	dpFlag := fs.String("data-plane-id", "", "logical data plane ID")
	connectorFlag := fs.String("connector-instance-id", "", "connector installation ID")
	identityFlag := fs.String("identity-file", "", "identity file")
	tokenFlag := fs.String("enrollment-token-file", "", "one-time token file")
	insecureFlag := fs.Bool("allow-insecure-development", false, "allow HTTP only for development")
	timeoutFlag := fs.String("http-timeout", "", "HTTP timeout")
	intervalFlag := fs.String("heartbeat-interval", "", "heartbeat interval")
	mcpProviderFlag := fs.String("mcp-provider", "", "MCP provider (disabled, docker, dataplane, or kubernetes)")
	sandboxProviderFlag := fs.String("sandbox-provider", "", "sandbox provider (disabled or kubernetes)")
	kubernetesNamespaceFlag := fs.String("kubernetes-namespace", "", "Kubernetes execution namespace")
	kubernetesKubeconfigFlag := fs.String("kubernetes-kubeconfig", "", "Kubernetes kubeconfig path")
	dockerRuntimeFlag := fs.String("docker-runtime", "", "local Docker/Podman runtime executable")
	dockerNetworkFlag := fs.String("docker-network", "", "local Docker network")
	dockerNamePrefixFlag := fs.String("docker-name-prefix", "", "managed Docker container prefix")
	dockerMaxContainersFlag := fs.Int("docker-max-containers", 0, "maximum managed Docker containers")
	sandboxLeaseTTLFlag := fs.String("sandbox-task-lease-ttl", "", "sandbox task lease TTL")
	sandboxStateRedisFlag := fs.String("sandbox-state-redis-url", "", "agent-local external sandbox state URL")
	if err := fs.Parse(args); err != nil {
		return Config{}, err
	}
	cfg := DefaultConfig()
	if *configPath != "" {
		if err := loadJSON(*configPath, &cfg); err != nil {
			return Config{}, err
		}
	}
	if err := applyEnv(&cfg); err != nil {
		return Config{}, err
	}
	if *urlFlag != "" {
		cfg.ControlPlaneURL = *urlFlag
	}
	if *connectorGatewayFlag != "" {
		cfg.ConnectorGatewayURL = *connectorGatewayFlag
	}
	if *dpFlag != "" {
		cfg.DataPlaneID = DataPlaneID(*dpFlag)
	}
	if *connectorFlag != "" {
		cfg.ConnectorInstanceID = ConnectorInstanceID(*connectorFlag)
	}
	if *identityFlag != "" {
		cfg.IdentityFile = *identityFlag
	}
	if *tokenFlag != "" {
		cfg.EnrollmentTokenFile = *tokenFlag
	}
	if *timeoutFlag != "" {
		cfg.HTTPTimeoutString = *timeoutFlag
	}
	if *intervalFlag != "" {
		cfg.HeartbeatIntervalString = *intervalFlag
	}
	if *mcpProviderFlag != "" {
		cfg.MCPProvider = *mcpProviderFlag
	}
	if *sandboxProviderFlag != "" {
		cfg.SandboxProvider = *sandboxProviderFlag
	}
	if *kubernetesNamespaceFlag != "" {
		cfg.KubernetesNamespace = *kubernetesNamespaceFlag
	}
	if *kubernetesKubeconfigFlag != "" {
		cfg.KubernetesKubeconfig = *kubernetesKubeconfigFlag
	}
	if *dockerRuntimeFlag != "" {
		cfg.DockerRuntime = *dockerRuntimeFlag
	}
	if *dockerNetworkFlag != "" {
		cfg.DockerNetwork = *dockerNetworkFlag
	}
	if *dockerNamePrefixFlag != "" {
		cfg.DockerNamePrefix = *dockerNamePrefixFlag
	}
	if *dockerMaxContainersFlag != 0 {
		cfg.DockerMaxContainers = *dockerMaxContainersFlag
	}
	if *sandboxLeaseTTLFlag != "" {
		cfg.SandboxTaskLeaseTTLString = *sandboxLeaseTTLFlag
	}
	if *sandboxStateRedisFlag != "" {
		cfg.SandboxStateRedisURL = *sandboxStateRedisFlag
	}
	flagProvided := false
	fs.Visit(func(visited *flag.Flag) {
		if visited.Name == "allow-insecure-development" {
			flagProvided = true
		}
	})
	if flagProvided {
		cfg.AllowInsecureDevelopment = *insecureFlag
	}
	if cfg.HTTPTimeoutString != "" {
		d, err := time.ParseDuration(cfg.HTTPTimeoutString)
		if err != nil {
			return Config{}, fmt.Errorf("invalid http_timeout: %w", err)
		}
		cfg.HTTPTimeout = d
	}
	if cfg.HeartbeatIntervalString != "" {
		d, err := time.ParseDuration(cfg.HeartbeatIntervalString)
		if err != nil {
			return Config{}, fmt.Errorf("invalid heartbeat_interval: %w", err)
		}
		cfg.HeartbeatInterval = d
	}
	if cfg.SandboxTaskLeaseTTLString != "" {
		d, err := time.ParseDuration(cfg.SandboxTaskLeaseTTLString)
		if err != nil || d <= 0 {
			return Config{}, fmt.Errorf("invalid sandbox_task_lease_ttl")
		}
		cfg.SandboxTaskLeaseTTL = d
	}
	if len(fs.Args()) != 0 {
		return Config{}, fmt.Errorf("unexpected positional arguments")
	}
	return cfg, cfg.Validate()
}

func loadJSON(path string, cfg *Config) error {
	f, err := os.Open(path)
	if err != nil {
		return fmt.Errorf("open config: %w", err)
	}
	defer f.Close()
	d := json.NewDecoder(f)
	d.DisallowUnknownFields()
	if err := d.Decode(cfg); err != nil {
		return fmt.Errorf("decode config: %w", err)
	}
	if d.Decode(&struct{}{}) != io.EOF {
		return errors.New("decode config: more than one JSON value")
	}
	return nil
}

func applyEnv(c *Config) error {
	set := func(key string, dst *string) {
		if v := os.Getenv(key); v != "" {
			*dst = v
		}
	}
	set("DATA_PLANE_AGENT_CONTROL_PLANE_URL", &c.ControlPlaneURL)
	set("DATA_PLANE_AGENT_CONNECTOR_GATEWAY_URL", &c.ConnectorGatewayURL)
	var dp, ci string
	set("DATA_PLANE_AGENT_DATA_PLANE_ID", &dp)
	set("DATA_PLANE_AGENT_CONNECTOR_INSTANCE_ID", &ci)
	c.DataPlaneID = DataPlaneID(first(dp, string(c.DataPlaneID)))
	c.ConnectorInstanceID = ConnectorInstanceID(first(ci, string(c.ConnectorInstanceID)))
	set("DATA_PLANE_AGENT_IDENTITY_FILE", &c.IdentityFile)
	set("DATA_PLANE_AGENT_ENROLLMENT_TOKEN_FILE", &c.EnrollmentTokenFile)
	set("DATA_PLANE_AGENT_HTTP_TIMEOUT", &c.HTTPTimeoutString)
	set("DATA_PLANE_AGENT_HEARTBEAT_INTERVAL", &c.HeartbeatIntervalString)
	set("DATA_PLANE_AGENT_MCP_PROVIDER", &c.MCPProvider)
	set("DATA_PLANE_AGENT_SANDBOX_PROVIDER", &c.SandboxProvider)
	set("DATA_PLANE_AGENT_KUBERNETES_NAMESPACE", &c.KubernetesNamespace)
	set("DATA_PLANE_AGENT_KUBERNETES_KUBECONFIG", &c.KubernetesKubeconfig)
	set("DATA_PLANE_AGENT_DOCKER_RUNTIME", &c.DockerRuntime)
	set("DATA_PLANE_AGENT_DOCKER_NETWORK", &c.DockerNetwork)
	set("DATA_PLANE_AGENT_DOCKER_NAME_PREFIX", &c.DockerNamePrefix)
	if v := os.Getenv("DATA_PLANE_AGENT_DOCKER_MAX_CONTAINERS"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil {
			return fmt.Errorf("invalid DATA_PLANE_AGENT_DOCKER_MAX_CONTAINERS: %w", err)
		}
		c.DockerMaxContainers = n
	}
	set("DATA_PLANE_AGENT_SANDBOX_TASK_LEASE_TTL", &c.SandboxTaskLeaseTTLString)
	set("DATA_PLANE_AGENT_SANDBOX_STATE_REDIS_URL", &c.SandboxStateRedisURL)
	set("DATA_PLANE_AGENT_VERSION", &c.AgentVersion)
	if v := os.Getenv("DATA_PLANE_AGENT_ALLOW_INSECURE_DEVELOPMENT"); v != "" {
		b, err := strconv.ParseBool(v)
		if err != nil {
			return fmt.Errorf("invalid DATA_PLANE_AGENT_ALLOW_INSECURE_DEVELOPMENT: %w", err)
		}
		c.AllowInsecureDevelopment = b
	}
	return nil
}
func first(a, b string) string {
	if a != "" {
		return a
	}
	return b
}

func (c Config) Validate() error {
	if strings.TrimSpace(c.ControlPlaneURL) == "" {
		return errors.New("control_plane_url is required")
	}
	if c.HTTPTimeout <= 0 || c.HeartbeatInterval <= 0 {
		return errors.New("http timeout and heartbeat interval must be positive")
	}
	u, err := url.Parse(c.ControlPlaneURL)
	if err != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return errors.New("invalid control_plane_url")
	}
	if u.Scheme != "https" && !(u.Scheme == "http" && c.AllowInsecureDevelopment && isLoopbackHostname(u.Hostname())) {
		return errors.New("control_plane_url must use HTTPS; development HTTP is limited to loopback")
	}
	if c.ConnectorGatewayURL != "" {
		gateway, err := url.Parse(c.ConnectorGatewayURL)
		if err != nil || gateway.Host == "" || gateway.User != nil || gateway.RawQuery != "" || gateway.Fragment != "" {
			return errors.New("invalid connector_gateway_url")
		}
		if gateway.Scheme != "https" && !(gateway.Scheme == "http" && c.AllowInsecureDevelopment && isLoopbackHostname(gateway.Hostname())) {
			return errors.New("connector_gateway_url must use HTTPS; development HTTP is limited to loopback")
		}
	}
	if c.IdentityFile == "" {
		return errors.New("identity_file is required")
	}
	if !filepath.IsAbs(c.IdentityFile) {
		return errors.New("identity_file must be an absolute path")
	}
	if c.DataPlaneID != "" {
		if _, err := uuid.Parse(string(c.DataPlaneID)); err != nil {
			return errors.New("data_plane_id must be a UUID")
		}
	}
	mcpProvider := strings.ToLower(strings.TrimSpace(c.MCPProvider))
	if mcpProvider == "" {
		mcpProvider = "disabled"
	}
	sandboxProvider := strings.ToLower(strings.TrimSpace(c.SandboxProvider))
	if sandboxProvider == "" {
		sandboxProvider = "disabled"
	}
	if err := validateProvider("mcp_provider", mcpProvider, "disabled", "docker", "dataplane", "kubernetes"); err != nil {
		return err
	}
	if err := validateProvider("sandbox_provider", sandboxProvider, "disabled", "kubernetes", "opensandbox", "e2b", "cube"); err != nil {
		return err
	}
	if (mcpProvider == "kubernetes" || sandboxProvider == "kubernetes") && strings.TrimSpace(c.KubernetesNamespace) == "" {
		return errors.New("kubernetes_namespace is required when a Kubernetes provider is configured")
	}
	if c.Capabilities.MCP && mcpProvider == "disabled" {
		return errors.New("MCP capability is advertised but mcp_provider is disabled")
	}
	if c.Capabilities.Sandbox && sandboxProvider == "disabled" {
		return errors.New("sandbox capability is advertised but sandbox_provider is disabled")
	}
	if sandboxProvider == "kubernetes" && c.SandboxTaskLeaseTTL <= 0 {
		return errors.New("sandbox_task_lease_ttl must be positive")
	}
	if sandboxProvider == "opensandbox" || sandboxProvider == "e2b" || sandboxProvider == "cube" {
		stateURL, err := url.Parse(c.SandboxStateRedisURL)
		if err != nil || stateURL.Host == "" || (stateURL.Scheme != "redis" && stateURL.Scheme != "rediss") {
			return errors.New("sandbox_state_redis_url must be an absolute redis or rediss URL for an external sandbox provider")
		}
	}
	if mcpProvider == "docker" {
		if strings.TrimSpace(c.DockerRuntime) == "" || strings.TrimSpace(c.DockerNamePrefix) == "" || c.DockerMaxContainers <= 0 {
			return errors.New("docker runtime, name prefix, and max containers are required for Docker MCP")
		}
	}
	return nil
}

func isLoopbackHostname(host string) bool {
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func validateProvider(name, value string, supported ...string) error {
	value = strings.ToLower(strings.TrimSpace(value))
	for _, candidate := range supported {
		if value == candidate {
			return nil
		}
	}
	return fmt.Errorf("unsupported %s=%q", name, value)
}
