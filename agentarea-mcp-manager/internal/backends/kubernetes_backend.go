package backends

import (
	"context"
	"fmt"
	"log/slog"
	"strconv"
	"strings"
	"time"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/kubernetes"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

// KubernetesBackend implements the Backend interface using Kubernetes resources
type KubernetesBackend struct {
	client       client.Client
	clientset    kubernetes.Interface
	config       *config.Config
	k8sConfig    *config.KubernetesConfig
	logger       *slog.Logger
	scheme       *runtime.Scheme
	taskLeaseTTL time.Duration
	// scratchSizeLimit bounds every ephemeral volume on a spawned instance pod.
	// Resolved once here so no code path can reach a pod with an unbounded one.
	scratchSizeLimit resource.Quantity
	// taskOperations fences composite task work against in-process retirement.
	taskOperations *sandboxruntime.TaskOperationGate
}

// NewKubernetesBackend creates a new Kubernetes backend
func NewKubernetesBackend(cfg *config.Config, logger *slog.Logger, taskLeaseTTL time.Duration) (*KubernetesBackend, error) {
	if taskLeaseTTL <= 0 {
		return nil, fmt.Errorf("sandbox task lease TTL must be positive")
	}
	scratchSizeLimit, err := cfg.Kubernetes.InstancePod.ScratchSizeLimitQuantity()
	if err != nil {
		return nil, err
	}
	k8sConfig, err := resolveClusterConfig(cfg.Kubernetes.Kubeconfig, logger)
	if err != nil {
		return nil, err
	}

	// Create controller-runtime client
	scheme := runtime.NewScheme()
	if err := corev1.AddToScheme(scheme); err != nil {
		return nil, fmt.Errorf("failed to add core/v1 to scheme: %w", err)
	}
	if err := appsv1.AddToScheme(scheme); err != nil {
		return nil, fmt.Errorf("failed to add apps/v1 to scheme: %w", err)
	}
	// Ingress and Gateway API types are deliberately absent: instances are
	// reachable only through the demand gateway, so this client never creates,
	// reads or deletes a route.

	runtimeClient, err := client.New(k8sConfig, client.Options{Scheme: scheme})
	if err != nil {
		return nil, fmt.Errorf("failed to create controller-runtime client: %w", err)
	}

	// Create clientset for additional operations
	clientset, err := kubernetes.NewForConfig(k8sConfig)
	if err != nil {
		return nil, fmt.Errorf("failed to create kubernetes clientset: %w", err)
	}

	return &KubernetesBackend{
		client:       runtimeClient,
		clientset:    clientset,
		config:       cfg,
		k8sConfig:    &cfg.Kubernetes,
		logger:       logger,
		scheme:       scheme,
		taskLeaseTTL: taskLeaseTTL,

		scratchSizeLimit: scratchSizeLimit,
		taskOperations:   sandboxruntime.NewTaskOperationGate("kubernetes"),
	}, nil
}

// Initialize initializes the Kubernetes backend
func (k *KubernetesBackend) Initialize(ctx context.Context) error {
	k.logger.Info("Initializing Kubernetes backend",
		slog.String("namespace", k.k8sConfig.Namespace),
		slog.String("domain", k.k8sConfig.Domain))

	// Ensure namespace exists
	if err := k.ensureNamespace(ctx); err != nil {
		return fmt.Errorf("failed to ensure namespace: %w", err)
	}
	k.logger.Info("Kubernetes backend initialized successfully")
	return nil
}

// CreateInstance creates a new MCP server instance using Kubernetes resources
func (k *KubernetesBackend) CreateInstance(ctx context.Context, spec *InstanceSpec) (*InstanceResult, error) {
	instanceName := k.sanitizeInstanceName(spec.Name)

	k.logger.Info("Creating Kubernetes instance",
		slog.String("name", spec.Name),
		slog.String("instance_name", instanceName),
		slog.String("image", spec.Image))

	// Idempotency: if a configmap already exists for this instanceName but
	// belongs to a DIFFERENT instance_id, delete ALL managed resources first
	// so the create starts clean. If it already belongs to THIS instance_id,
	// the resources are already provisioned — return success immediately.
	existingCM := &corev1.ConfigMap{}
	cmName := fmt.Sprintf("mcp-%s", instanceName)
	cmErr := k.client.Get(ctx, types.NamespacedName{Namespace: k.k8sConfig.Namespace, Name: cmName}, existingCM)
	if cmErr != nil && !errors.IsNotFound(cmErr) {
		return nil, fmt.Errorf("failed to check for existing resources: %w", cmErr)
	}
	if cmErr == nil {
		existingID := existingCM.Data["instance-id"]
		if existingID == spec.InstanceID {
			complete, graphErr := k.instanceResourceGraphComplete(ctx, instanceName)
			if graphErr != nil {
				return nil, graphErr
			}
			if complete {
				k.logger.Info("Resources already exist for this instance — returning early (idempotent)",
					slog.String("instance_id", spec.InstanceID))
				return &InstanceResult{
					ID:          spec.InstanceID,
					Name:        spec.Name,
					URL:         k.k8sConfig.GetInstanceURL(instanceName),
					InternalURL: k.k8sConfig.GetInternalServiceURL(instanceName, spec.Port),
					Status:      "starting",
					CreatedAt:   time.Now(),
				}, nil
			}
			// Recreate the complete graph atomically from the manager's point of
			// view. A ready Deployment without its Secret or Service is not a
			// usable/idempotent instance.
			k.logger.Warn("MCP resource graph is incomplete, re-creating",
				slog.String("instance_id", spec.InstanceID))
			if err := k.cleanupResources(ctx, instanceName); err != nil {
				return nil, fmt.Errorf("failed to clean up partial resources for %s: %w", instanceName, err)
			}
		} else {
			// Different instance owns these resources — clean up before re-creating.
			k.logger.Info("Stale resources found for different instance, cleaning up",
				slog.String("instance_name", instanceName),
				slog.String("existing_instance_id", existingID),
				slog.String("new_instance_id", spec.InstanceID))
			if err := k.cleanupResources(ctx, instanceName); err != nil {
				return nil, fmt.Errorf("failed to clean up stale resources for %s: %w", instanceName, err)
			}
		}
	}

	// Create resources in order
	resources := []func(context.Context, string, *InstanceSpec) error{
		k.createConfigMap,
		k.createSecret,
		k.createDeployment,
		k.createService,
	}

	for _, createFunc := range resources {
		if err := createFunc(ctx, instanceName, spec); err != nil {
			k.logger.Error("Failed to create resource, cleaning up",
				slog.String("instance_name", instanceName),
				slog.String("error", err.Error()))

			// Best effort cleanup — log but don't override the original error
			if cleanupErr := k.cleanupResources(ctx, instanceName); cleanupErr != nil {
				k.logger.Warn("Cleanup after failed create also failed",
					slog.String("instance_name", instanceName),
					slog.String("cleanup_error", cleanupErr.Error()))
			}
			return nil, fmt.Errorf("failed to create kubernetes resources: %w", err)
		}
	}

	// Return immediately (ack-only) — Python's verify() retries list_tools
	// until the pod is ready, which can take > 60s on cold pulls. Blocking
	// here until the deployment is Ready causes the caller's HTTP timeout to
	// fire, which cancels this context and triggers spurious cleanup.
	result := &InstanceResult{
		ID:          spec.InstanceID,
		Name:        spec.Name,
		URL:         k.k8sConfig.GetInstanceURL(instanceName),
		InternalURL: k.k8sConfig.GetInternalServiceURL(instanceName, spec.Port),
		Status:      "starting",
		CreatedAt:   time.Now(),
	}

	k.logger.Info("Successfully created Kubernetes instance",
		slog.String("id", result.ID),
		slog.String("name", result.Name),
		slog.String("url", result.URL))

	return result, nil
}

func (k *KubernetesBackend) instanceResourceGraphComplete(ctx context.Context, instanceName string) (bool, error) {
	name := fmt.Sprintf("mcp-%s", instanceName)
	key := types.NamespacedName{Namespace: k.k8sConfig.Namespace, Name: name}
	objects := []client.Object{
		&corev1.ConfigMap{},
		&corev1.Secret{},
		&appsv1.Deployment{},
		&corev1.Service{},
	}
	for _, object := range objects {
		if err := k.client.Get(ctx, key, object); err != nil {
			if errors.IsNotFound(err) {
				return false, nil
			}
			return false, fmt.Errorf("inspect MCP resource graph %s: %w", name, err)
		}
	}
	return true, nil
}

// DeleteInstance removes an MCP server instance and all its Kubernetes resources
func (k *KubernetesBackend) DeleteInstance(ctx context.Context, instanceID string) error {
	instanceName, err := k.findInstanceNameByID(ctx, instanceID)
	if err != nil {
		return fmt.Errorf("failed to find instance: %w", err)
	}

	k.logger.Info("Deleting Kubernetes instance",
		slog.String("instance_id", instanceID),
		slog.String("instance_name", instanceName))

	if err := k.cleanupResources(ctx, instanceName); err != nil {
		return fmt.Errorf("failed to cleanup resources: %w", err)
	}

	k.logger.Info("Successfully deleted Kubernetes instance",
		slog.String("instance_id", instanceID),
		slog.String("instance_name", instanceName))

	return nil
}

// GetInstanceStatus retrieves the current status of a Kubernetes instance
func (k *KubernetesBackend) GetInstanceStatus(ctx context.Context, instanceID string) (*InstanceStatus, error) {
	instanceName, err := k.findInstanceNameByID(ctx, instanceID)
	if err != nil {
		return nil, fmt.Errorf("failed to find instance: %w", err)
	}
	complete, err := k.instanceResourceGraphComplete(ctx, instanceName)
	if err != nil {
		return nil, err
	}
	if !complete {
		return nil, fmt.Errorf("%w: incomplete Kubernetes resource graph for %s", ErrInstanceNotFound, instanceID)
	}

	// Get deployment
	deployment := &appsv1.Deployment{}
	if err := k.client.Get(ctx, types.NamespacedName{
		Namespace: k.k8sConfig.Namespace,
		Name:      fmt.Sprintf("mcp-%s", instanceName),
	}, deployment); err != nil {
		if errors.IsNotFound(err) {
			return nil, fmt.Errorf("%w: %s", ErrInstanceNotFound, instanceID)
		}
		return nil, fmt.Errorf("failed to get deployment: %w", err)
	}

	// Get configmap for metadata
	configMap := &corev1.ConfigMap{}
	if err := k.client.Get(ctx, types.NamespacedName{
		Namespace: k.k8sConfig.Namespace,
		Name:      fmt.Sprintf("mcp-%s", instanceName),
	}, configMap); err != nil {
		k.logger.Warn("Failed to get configmap for metadata",
			slog.String("instance_name", instanceName),
			slog.String("error", err.Error()))
	}

	// Determine status from deployment conditions
	status := k.getDeploymentStatus(deployment)

	// Extract port from configmap
	port := 8000
	if configMap.Data != nil {
		if portStr, exists := configMap.Data["port"]; exists {
			if p, err := strconv.Atoi(portStr); err == nil {
				port = p
			}
		}
	}

	// Extract image from deployment
	image := ""
	if len(deployment.Spec.Template.Spec.Containers) > 0 {
		image = deployment.Spec.Template.Spec.Containers[0].Image
	}

	// Get environment variables from secret
	environment := make(map[string]string)
	secret := &corev1.Secret{}
	if err := k.client.Get(ctx, types.NamespacedName{
		Namespace: k.k8sConfig.Namespace,
		Name:      fmt.Sprintf("mcp-%s", instanceName),
	}, secret); err == nil {
		for key := range secret.Data {
			environment[key] = "[REDACTED]" // Don't expose secret values
		}
	}

	instanceStatus := &InstanceStatus{
		ID:          string(deployment.UID),
		Name:        instanceName,
		ServiceName: instanceName,
		Status:      status,
		URL:         k.k8sConfig.GetInstanceURL(instanceName),
		InternalURL: k.k8sConfig.GetInternalServiceURL(instanceName, port),
		Image:       image,
		Port:        port,
		Environment: environment,
		Labels:      deployment.Labels,
		CreatedAt:   deployment.CreationTimestamp.Time,
		UpdatedAt:   time.Now(),
	}

	// Perform health check if instance is running
	if status == "running" {
		if healthResult, err := k.PerformHealthCheck(ctx, instanceID); err == nil {
			instanceStatus.HealthStatus = healthResult
		}
	}

	return instanceStatus, nil
}

// ListInstances returns all managed Kubernetes instances
func (k *KubernetesBackend) ListInstances(ctx context.Context) ([]*InstanceStatus, error) {
	deployments := &appsv1.DeploymentList{}
	if err := k.client.List(ctx, deployments, client.InNamespace(k.k8sConfig.Namespace), client.MatchingLabels{
		"app.kubernetes.io/managed-by": "mcp-manager",
		"app.kubernetes.io/component":  "mcp-server",
	}); err != nil {
		return nil, fmt.Errorf("failed to list deployments: %w", err)
	}

	instances := make([]*InstanceStatus, 0, len(deployments.Items))
	for _, deployment := range deployments.Items {
		instanceName := strings.TrimPrefix(deployment.Name, "mcp-")

		status, err := k.GetInstanceStatus(ctx, string(deployment.UID))
		if err != nil {
			k.logger.Warn("Failed to get instance status",
				slog.String("instance_name", instanceName),
				slog.String("error", err.Error()))
			continue
		}

		instances = append(instances, status)
	}

	return instances, nil
}

// UpdateInstance updates an existing Kubernetes instance
func (k *KubernetesBackend) UpdateInstance(ctx context.Context, instanceID string, spec *InstanceSpec) error {
	instanceName, err := k.findInstanceNameByID(ctx, instanceID)
	if err != nil {
		return fmt.Errorf("failed to find instance: %w", err)
	}

	k.logger.Info("Updating Kubernetes instance",
		slog.String("instance_id", instanceID),
		slog.String("instance_name", instanceName))

	// Update configmap
	if err := k.updateConfigMap(ctx, instanceName, spec); err != nil {
		return fmt.Errorf("failed to update configmap: %w", err)
	}

	// Update secret
	if err := k.updateSecret(ctx, instanceName, spec); err != nil {
		return fmt.Errorf("failed to update secret: %w", err)
	}

	// Update deployment (this will trigger a rolling update)
	if err := k.updateDeployment(ctx, instanceName, spec); err != nil {
		return fmt.Errorf("failed to update deployment: %w", err)
	}

	k.logger.Info("Successfully updated Kubernetes instance",
		slog.String("instance_id", instanceID),
		slog.String("instance_name", instanceName))

	return nil
}

// PerformHealthCheck performs health check on a Kubernetes instance
func (k *KubernetesBackend) PerformHealthCheck(ctx context.Context, instanceID string) (*HealthCheckResult, error) {
	instanceName, err := k.findInstanceNameByID(ctx, instanceID)
	if err != nil {
		return nil, fmt.Errorf("failed to find instance: %w", err)
	}

	// Get deployment status
	deployment := &appsv1.Deployment{}
	if err := k.client.Get(ctx, types.NamespacedName{
		Namespace: k.k8sConfig.Namespace,
		Name:      fmt.Sprintf("mcp-%s", instanceName),
	}, deployment); err != nil {
		if errors.IsNotFound(err) {
			return k.performWarmPodHealthCheck(ctx, instanceName)
		}
		return &HealthCheckResult{
			Healthy:     false,
			Status:      "error",
			ServiceName: instanceName,
			Error:       fmt.Sprintf("failed to get deployment: %v", err),
			Timestamp:   time.Now(),
		}, nil
	}

	// Check deployment readiness
	ready := deployment.Status.ReadyReplicas > 0 &&
		deployment.Status.ReadyReplicas == deployment.Status.Replicas

	result := &HealthCheckResult{
		Healthy:     ready,
		Status:      k.getDeploymentStatus(deployment),
		ServiceName: instanceName,
		Timestamp:   time.Now(),
	}

	// If deployment is ready, try HTTP health check
	if ready {
		httpHealthy, responseTime := k.performHTTPHealthCheck(ctx, instanceName)
		result.HTTPReachable = httpHealthy
		result.ResponseTime = responseTime
		result.Healthy = ready && httpHealthy
	}

	return result, nil
}

func (k *KubernetesBackend) performWarmPodHealthCheck(ctx context.Context, instanceName string) (*HealthCheckResult, error) {
	pods := &corev1.PodList{}
	if err := k.client.List(ctx, pods, client.InNamespace(k.k8sConfig.Namespace), client.MatchingLabels{
		"mcp.agentarea.io/instance-name": instanceName,
	}); err != nil {
		return nil, fmt.Errorf("failed to list warm pods: %w", err)
	}
	if len(pods.Items) == 0 {
		return &HealthCheckResult{
			Healthy:     false,
			Status:      "error",
			ServiceName: instanceName,
			Error:       "warm pod not found",
			Timestamp:   time.Now(),
		}, nil
	}

	pod := pods.Items[0]
	ready := pod.Status.Phase == corev1.PodRunning && pod.Labels["mcp.agentarea.io/status"] == "ready"
	result := &HealthCheckResult{
		Healthy:     ready,
		Status:      pod.Labels["mcp.agentarea.io/status"],
		ServiceName: instanceName,
		Timestamp:   time.Now(),
	}
	if ready {
		httpHealthy, responseTime := k.performHTTPHealthCheck(ctx, instanceName)
		result.HTTPReachable = httpHealthy
		result.ResponseTime = responseTime
		result.Healthy = httpHealthy
	}
	return result, nil
}

// Shutdown gracefully shuts down the Kubernetes backend
func (k *KubernetesBackend) Shutdown(ctx context.Context) error {
	k.logger.Info("Shutting down Kubernetes backend")
	// No specific cleanup needed for Kubernetes client
	return nil
}

// Helper methods

// sanitizeInstanceName sanitizes an instance name for Kubernetes
func (k *KubernetesBackend) sanitizeInstanceName(name string) string {
	// Kubernetes names must be lowercase and contain only alphanumeric characters and hyphens
	sanitized := strings.ToLower(name)
	sanitized = strings.ReplaceAll(sanitized, "_", "-")
	sanitized = strings.ReplaceAll(sanitized, " ", "-")

	// Remove any non-alphanumeric characters except hyphens
	var result strings.Builder
	for _, r := range sanitized {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') || r == '-' {
			result.WriteRune(r)
		}
	}

	sanitized = result.String()

	// Trim leading/trailing hyphens
	sanitized = strings.Trim(sanitized, "-")

	// Ensure it's not empty and doesn't exceed 253 characters
	if sanitized == "" {
		sanitized = "instance"
	}
	if len(sanitized) > 253 {
		sanitized = sanitized[:253]
		sanitized = strings.TrimSuffix(sanitized, "-")
	}

	return sanitized
}

// ensureNamespace creates the namespace if it doesn't exist
func (k *KubernetesBackend) ensureNamespace(ctx context.Context) error {
	namespace := &corev1.Namespace{}
	err := k.client.Get(ctx, types.NamespacedName{Name: k.k8sConfig.Namespace}, namespace)
	if err != nil {
		if errors.IsNotFound(err) {
			// Create namespace
			namespace = &corev1.Namespace{
				ObjectMeta: metav1.ObjectMeta{
					Name: k.k8sConfig.Namespace,
					Labels: map[string]string{
						"app.kubernetes.io/managed-by": "mcp-manager",
					},
				},
			}
			if err := k.client.Create(ctx, namespace); err != nil {
				return fmt.Errorf("failed to create namespace: %w", err)
			}
			k.logger.Info("Created namespace", slog.String("namespace", k.k8sConfig.Namespace))
		} else {
			return fmt.Errorf("failed to get namespace: %w", err)
		}
	}
	return nil
}

// Common labels for all resources
func (k *KubernetesBackend) getCommonLabels(instanceName string) map[string]string {
	return map[string]string{
		"app.kubernetes.io/name":       "mcp-server",
		"app.kubernetes.io/instance":   instanceName,
		"app.kubernetes.io/component":  "mcp-server",
		"app.kubernetes.io/managed-by": "mcp-manager",
		"agentarea.io/instance":        instanceName,
	}
}

// Continue in next message due to length...
