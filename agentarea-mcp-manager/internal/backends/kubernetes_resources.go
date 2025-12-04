package backends

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/agentarea/mcp-manager/internal/config"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	networkingv1 "k8s.io/api/networking/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/intstr"
	"k8s.io/apimachinery/pkg/util/wait"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

// createConfigMap creates a ConfigMap for the MCP instance
func (k *KubernetesBackend) createConfigMap(ctx context.Context, instanceName string, spec *InstanceSpec) error {
	configMap := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("mcp-%s", instanceName),
			Namespace: k.k8sConfig.Namespace,
			Labels:    k.getCommonLabels(instanceName),
		},
		Data: map[string]string{
			"instance-id":   spec.InstanceID,
			"service-name":  spec.ServiceName,
			"port":          strconv.Itoa(spec.Port),
			"workspace-id":  spec.WorkspaceID,
		},
	}

	if err := k.client.Create(ctx, configMap); err != nil {
		return fmt.Errorf("failed to create configmap: %w", err)
	}

	return nil
}

// createSecret creates a Secret for environment variables
func (k *KubernetesBackend) createSecret(ctx context.Context, instanceName string, spec *InstanceSpec) error {
	secretData := make(map[string][]byte)
	
	// Add environment variables
	for key, value := range spec.Environment {
		secretData[key] = []byte(value)
	}
	
	// Add MCP-specific environment variables
	secretData["MCP_INSTANCE_ID"] = []byte(spec.InstanceID)
	secretData["MCP_SERVICE_NAME"] = []byte(spec.ServiceName)
	secretData["MCP_CONTAINER_PORT"] = []byte(strconv.Itoa(spec.Port))

	secret := &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("mcp-%s", instanceName),
			Namespace: k.k8sConfig.Namespace,
			Labels:    k.getCommonLabels(instanceName),
		},
		Type: corev1.SecretTypeOpaque,
		Data: secretData,
	}

	if err := k.client.Create(ctx, secret); err != nil {
		return fmt.Errorf("failed to create secret: %w", err)
	}

	return nil
}

// createDeployment creates a Deployment for the MCP server
func (k *KubernetesBackend) createDeployment(ctx context.Context, instanceName string, spec *InstanceSpec) error {
	labels := k.getCommonLabels(instanceName)
	
	// Convert ResourceList to config.ResourceRequirements
	var configRequests, configLimits *config.ResourceRequirements
	if spec.Resources.Requests.CPU != "" || spec.Resources.Requests.Memory != "" {
		configRequests = &config.ResourceRequirements{
			CPU:    spec.Resources.Requests.CPU,
			Memory: spec.Resources.Requests.Memory,
		}
	}
	if spec.Resources.Limits.CPU != "" || spec.Resources.Limits.Memory != "" {
		configLimits = &config.ResourceRequirements{
			CPU:    spec.Resources.Limits.CPU,
			Memory: spec.Resources.Limits.Memory,
		}
	}

	// Resource requirements
	requests := k.k8sConfig.GetResourceRequirements(configRequests, nil)
	limits := k.k8sConfig.GetResourceLimits(configLimits)
	
	resourceRequirements := corev1.ResourceRequirements{
		Requests: corev1.ResourceList{},
		Limits:   corev1.ResourceList{},
	}
	
	if requests.CPU != "" {
		resourceRequirements.Requests[corev1.ResourceCPU] = resource.MustParse(requests.CPU)
	}
	if requests.Memory != "" {
		resourceRequirements.Requests[corev1.ResourceMemory] = resource.MustParse(requests.Memory)
	}
	if limits.CPU != "" {
		resourceRequirements.Limits[corev1.ResourceCPU] = resource.MustParse(limits.CPU)
	}
	if limits.Memory != "" {
		resourceRequirements.Limits[corev1.ResourceMemory] = resource.MustParse(limits.Memory)
	}

	// Security context
	securityContext := &corev1.SecurityContext{
		RunAsNonRoot:             &k.k8sConfig.SecurityContext.RunAsNonRoot,
		RunAsUser:                &k.k8sConfig.SecurityContext.RunAsUser,
		ReadOnlyRootFilesystem:   &k.k8sConfig.SecurityContext.ReadOnlyRootFilesystem,
		AllowPrivilegeEscalation: &k.k8sConfig.SecurityContext.AllowPrivilegeEscalation,
		Capabilities: &corev1.Capabilities{
			Drop: []corev1.Capability{},
		},
	}
	
	for _, cap := range k.k8sConfig.SecurityContext.DropCapabilities {
		securityContext.Capabilities.Drop = append(securityContext.Capabilities.Drop, corev1.Capability(cap))
	}

	// Container definition
	container := corev1.Container{
		Name:  "mcp-server",
		Image: spec.Image,
		Ports: []corev1.ContainerPort{
			{
				Name:          "http",
				ContainerPort: int32(spec.Port),
				Protocol:      corev1.ProtocolTCP,
			},
		},
		EnvFrom: []corev1.EnvFromSource{
			{
				SecretRef: &corev1.SecretEnvSource{
					LocalObjectReference: corev1.LocalObjectReference{
						Name: fmt.Sprintf("mcp-%s", instanceName),
					},
				},
			},
			{
				ConfigMapRef: &corev1.ConfigMapEnvSource{
					LocalObjectReference: corev1.LocalObjectReference{
						Name: fmt.Sprintf("mcp-%s", instanceName),
					},
				},
			},
		},
		Resources:       resourceRequirements,
		SecurityContext: securityContext,
		LivenessProbe: &corev1.Probe{
			ProbeHandler: corev1.ProbeHandler{
				HTTPGet: &corev1.HTTPGetAction{
					Path: "/health",
					Port: intstr.FromInt(spec.Port),
				},
			},
			InitialDelaySeconds: 30,
			PeriodSeconds:       10,
			TimeoutSeconds:      5,
			FailureThreshold:    3,
		},
		ReadinessProbe: &corev1.Probe{
			ProbeHandler: corev1.ProbeHandler{
				HTTPGet: &corev1.HTTPGetAction{
					Path: "/ready",
					Port: intstr.FromInt(spec.Port),
				},
			},
			InitialDelaySeconds: 5,
			PeriodSeconds:       5,
			TimeoutSeconds:      3,
			FailureThreshold:    3,
		},
	}

	// Add custom command if specified
	if len(spec.Command) > 0 {
		container.Command = spec.Command
	}

	// Volume mounts for writable directories (since we use read-only root filesystem)
	volumeMounts := []corev1.VolumeMount{
		{
			Name:      "tmp",
			MountPath: "/tmp",
		},
		{
			Name:      "var-run",
			MountPath: "/var/run",
		},
	}

	// Add user-specified writable paths
	for i, path := range spec.WritablePaths {
		volumeName := fmt.Sprintf("writable-%d", i)
		volumeMounts = append(volumeMounts, corev1.VolumeMount{
			Name:      volumeName,
			MountPath: path,
		})
	}

	container.VolumeMounts = volumeMounts

	deployment := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("mcp-%s", instanceName),
			Namespace: k.k8sConfig.Namespace,
			Labels:    labels,
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: int32Ptr(1),
			Selector: &metav1.LabelSelector{
				MatchLabels: map[string]string{
					"app.kubernetes.io/name":     "mcp-server",
					"app.kubernetes.io/instance": instanceName,
				},
			},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: labels,
				},
				Spec: corev1.PodSpec{
					SecurityContext: &corev1.PodSecurityContext{
						RunAsNonRoot: &k.k8sConfig.SecurityContext.RunAsNonRoot,
						RunAsUser:    &k.k8sConfig.SecurityContext.RunAsUser,
					},
					Containers: []corev1.Container{container},
					Volumes:    k.createVolumes(spec),
				},
			},
		},
	}

	// Add resource annotations
	if deployment.Spec.Template.ObjectMeta.Annotations == nil {
		deployment.Spec.Template.ObjectMeta.Annotations = make(map[string]string)
	}
	deployment.Spec.Template.ObjectMeta.Annotations["agentarea.io/instance-id"] = spec.InstanceID
	deployment.Spec.Template.ObjectMeta.Annotations["agentarea.io/workspace-id"] = spec.WorkspaceID

	if err := k.client.Create(ctx, deployment); err != nil {
		return fmt.Errorf("failed to create deployment: %w", err)
	}

	return nil
}

// createVolumes creates the volume specifications for writable directories
func (k *KubernetesBackend) createVolumes(spec *InstanceSpec) []corev1.Volume {
	// Default volumes (always needed for security)
	volumes := []corev1.Volume{
		{
			Name: "tmp",
			VolumeSource: corev1.VolumeSource{
				EmptyDir: &corev1.EmptyDirVolumeSource{},
			},
		},
		{
			Name: "var-run",
			VolumeSource: corev1.VolumeSource{
				EmptyDir: &corev1.EmptyDirVolumeSource{},
			},
		},
	}

	// Add user-specified writable paths as EmptyDir volumes
	for i := range spec.WritablePaths {
		volumeName := fmt.Sprintf("writable-%d", i)
		volumes = append(volumes, corev1.Volume{
			Name: volumeName,
			VolumeSource: corev1.VolumeSource{
				EmptyDir: &corev1.EmptyDirVolumeSource{},
			},
		})
	}

	return volumes
}

// createService creates a Service for the MCP server
func (k *KubernetesBackend) createService(ctx context.Context, instanceName string, spec *InstanceSpec) error {
	service := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("mcp-%s", instanceName),
			Namespace: k.k8sConfig.Namespace,
			Labels:    k.getCommonLabels(instanceName),
		},
		Spec: corev1.ServiceSpec{
			Selector: map[string]string{
				"app.kubernetes.io/name":     "mcp-server",
				"app.kubernetes.io/instance": instanceName,
			},
			Ports: []corev1.ServicePort{
				{
					Name:       "http",
					Port:       80,
					TargetPort: intstr.FromInt(spec.Port),
					Protocol:   corev1.ProtocolTCP,
				},
			},
			Type: corev1.ServiceTypeClusterIP,
		},
	}

	// Add metrics port if monitoring is enabled
	if k.k8sConfig.Monitoring.Enabled {
		service.Spec.Ports = append(service.Spec.Ports, corev1.ServicePort{
			Name:       "metrics",
			Port:       int32(k.k8sConfig.Monitoring.Metrics.Port),
			TargetPort: intstr.FromInt(k.k8sConfig.Monitoring.Metrics.Port),
			Protocol:   corev1.ProtocolTCP,
		})
	}

	if err := k.client.Create(ctx, service); err != nil {
		return fmt.Errorf("failed to create service: %w", err)
	}

	return nil
}

// createIngress creates an Ingress for external access
func (k *KubernetesBackend) createIngress(ctx context.Context, instanceName string, spec *InstanceSpec) error {
	pathType := networkingv1.PathTypePrefix
	
	ingress := &networkingv1.Ingress{
		ObjectMeta: metav1.ObjectMeta{
			Name:        fmt.Sprintf("mcp-%s", instanceName),
			Namespace:   k.k8sConfig.Namespace,
			Labels:      k.getCommonLabels(instanceName),
			Annotations: k.k8sConfig.GetIngressAnnotations(),
		},
		Spec: networkingv1.IngressSpec{
			IngressClassName: &k.k8sConfig.IngressClass,
			Rules: []networkingv1.IngressRule{
				{
					Host: k.k8sConfig.Domain,
					IngressRuleValue: networkingv1.IngressRuleValue{
						HTTP: &networkingv1.HTTPIngressRuleValue{
							Paths: []networkingv1.HTTPIngressPath{
								{
									Path:     fmt.Sprintf("/mcp/%s(/|$)(.*)", instanceName),
									PathType: &pathType,
									Backend: networkingv1.IngressBackend{
										Service: &networkingv1.IngressServiceBackend{
											Name: fmt.Sprintf("mcp-%s", instanceName),
											Port: networkingv1.ServiceBackendPort{
												Number: 80,
											},
										},
									},
								},
							},
						},
					},
				},
			},
		},
	}

	// Add TLS configuration if enabled
	if k.k8sConfig.TLS.Enabled {
		ingress.Spec.TLS = []networkingv1.IngressTLS{
			{
				Hosts:      []string{k.k8sConfig.Domain},
				SecretName: k.k8sConfig.TLS.SecretName,
			},
		}
	}

	if err := k.client.Create(ctx, ingress); err != nil {
		return fmt.Errorf("failed to create ingress: %w", err)
	}

	return nil
}

// waitForDeploymentReady waits for the deployment to be ready
func (k *KubernetesBackend) waitForDeploymentReady(ctx context.Context, instanceName string) error {
	deploymentName := fmt.Sprintf("mcp-%s", instanceName)
	
	return wait.PollUntilContextTimeout(ctx, 5*time.Second, k.k8sConfig.DeploymentTimeout, true, func(ctx context.Context) (bool, error) {
		deployment := &appsv1.Deployment{}
		if err := k.client.Get(ctx, types.NamespacedName{
			Namespace: k.k8sConfig.Namespace,
			Name:      deploymentName,
		}, deployment); err != nil {
			return false, err
		}

		// Check if deployment is ready
		return deployment.Status.ReadyReplicas > 0 && 
			   deployment.Status.ReadyReplicas == deployment.Status.Replicas, nil
	})
}

// cleanupResources removes all resources for an instance
func (k *KubernetesBackend) cleanupResources(ctx context.Context, instanceName string) error {
	resourceName := fmt.Sprintf("mcp-%s", instanceName)
	
	// Delete resources in reverse order
	resources := []client.Object{
		&networkingv1.Ingress{
			ObjectMeta: metav1.ObjectMeta{
				Name:      resourceName,
				Namespace: k.k8sConfig.Namespace,
			},
		},
		&corev1.Service{
			ObjectMeta: metav1.ObjectMeta{
				Name:      resourceName,
				Namespace: k.k8sConfig.Namespace,
			},
		},
		&appsv1.Deployment{
			ObjectMeta: metav1.ObjectMeta{
				Name:      resourceName,
				Namespace: k.k8sConfig.Namespace,
			},
		},
		&corev1.Secret{
			ObjectMeta: metav1.ObjectMeta{
				Name:      resourceName,
				Namespace: k.k8sConfig.Namespace,
			},
		},
		&corev1.ConfigMap{
			ObjectMeta: metav1.ObjectMeta{
				Name:      resourceName,
				Namespace: k.k8sConfig.Namespace,
			},
		},
	}

	var lastError error
	for _, resource := range resources {
		if err := k.client.Delete(ctx, resource); err != nil && !errors.IsNotFound(err) {
			k.logger.Warn("Failed to delete resource",
				slog.String("resource", fmt.Sprintf("%T", resource)),
				slog.String("name", resourceName),
				slog.String("error", err.Error()))
			lastError = err
		}
	}

	return lastError
}

// Update methods

// updateConfigMap updates the ConfigMap for an instance
func (k *KubernetesBackend) updateConfigMap(ctx context.Context, instanceName string, spec *InstanceSpec) error {
	configMap := &corev1.ConfigMap{}
	if err := k.client.Get(ctx, types.NamespacedName{
		Namespace: k.k8sConfig.Namespace,
		Name:      fmt.Sprintf("mcp-%s", instanceName),
	}, configMap); err != nil {
		return fmt.Errorf("failed to get configmap: %w", err)
	}

	// Update data
	configMap.Data["port"] = strconv.Itoa(spec.Port)
	configMap.Data["workspace-id"] = spec.WorkspaceID

	if err := k.client.Update(ctx, configMap); err != nil {
		return fmt.Errorf("failed to update configmap: %w", err)
	}

	return nil
}

// updateSecret updates the Secret for an instance
func (k *KubernetesBackend) updateSecret(ctx context.Context, instanceName string, spec *InstanceSpec) error {
	secret := &corev1.Secret{}
	if err := k.client.Get(ctx, types.NamespacedName{
		Namespace: k.k8sConfig.Namespace,
		Name:      fmt.Sprintf("mcp-%s", instanceName),
	}, secret); err != nil {
		return fmt.Errorf("failed to get secret: %w", err)
	}

	// Update data
	secretData := make(map[string][]byte)
	for key, value := range spec.Environment {
		secretData[key] = []byte(value)
	}
	secretData["MCP_INSTANCE_ID"] = []byte(spec.InstanceID)
	secretData["MCP_SERVICE_NAME"] = []byte(spec.ServiceName)
	secretData["MCP_CONTAINER_PORT"] = []byte(strconv.Itoa(spec.Port))

	secret.Data = secretData

	if err := k.client.Update(ctx, secret); err != nil {
		return fmt.Errorf("failed to update secret: %w", err)
	}

	return nil
}

// updateDeployment updates the Deployment for an instance
func (k *KubernetesBackend) updateDeployment(ctx context.Context, instanceName string, spec *InstanceSpec) error {
	deployment := &appsv1.Deployment{}
	if err := k.client.Get(ctx, types.NamespacedName{
		Namespace: k.k8sConfig.Namespace,
		Name:      fmt.Sprintf("mcp-%s", instanceName),
	}, deployment); err != nil {
		return fmt.Errorf("failed to get deployment: %w", err)
	}

	// Update container image and command if needed
	if len(deployment.Spec.Template.Spec.Containers) > 0 {
		container := &deployment.Spec.Template.Spec.Containers[0]
		container.Image = spec.Image
		
		if len(spec.Command) > 0 {
			container.Command = spec.Command
		}

		// Convert ResourceList to config.ResourceRequirements
		var configRequests, configLimits *config.ResourceRequirements
		if spec.Resources.Requests.CPU != "" || spec.Resources.Requests.Memory != "" {
			configRequests = &config.ResourceRequirements{
				CPU:    spec.Resources.Requests.CPU,
				Memory: spec.Resources.Requests.Memory,
			}
		}
		if spec.Resources.Limits.CPU != "" || spec.Resources.Limits.Memory != "" {
			configLimits = &config.ResourceRequirements{
				CPU:    spec.Resources.Limits.CPU,
				Memory: spec.Resources.Limits.Memory,
			}
		}

		// Update resource requirements
		requests := k.k8sConfig.GetResourceRequirements(configRequests, nil)
		limits := k.k8sConfig.GetResourceLimits(configLimits)
		
		if requests.CPU != "" {
			container.Resources.Requests[corev1.ResourceCPU] = resource.MustParse(requests.CPU)
		}
		if requests.Memory != "" {
			container.Resources.Requests[corev1.ResourceMemory] = resource.MustParse(requests.Memory)
		}
		if limits.CPU != "" {
			container.Resources.Limits[corev1.ResourceCPU] = resource.MustParse(limits.CPU)
		}
		if limits.Memory != "" {
			container.Resources.Limits[corev1.ResourceMemory] = resource.MustParse(limits.Memory)
		}
	}

	// Update annotations to trigger rolling update
	if deployment.Spec.Template.ObjectMeta.Annotations == nil {
		deployment.Spec.Template.ObjectMeta.Annotations = make(map[string]string)
	}
	deployment.Spec.Template.ObjectMeta.Annotations["agentarea.io/updated-at"] = time.Now().Format(time.RFC3339)

	if err := k.client.Update(ctx, deployment); err != nil {
		return fmt.Errorf("failed to update deployment: %w", err)
	}

	return nil
}

// Helper functions

// findInstanceNameByID finds instance name by deployment UID or instance ID
func (k *KubernetesBackend) findInstanceNameByID(ctx context.Context, instanceID string) (string, error) {
	deployments := &appsv1.DeploymentList{}
	if err := k.client.List(ctx, deployments, client.InNamespace(k.k8sConfig.Namespace), client.MatchingLabels{
		"app.kubernetes.io/managed-by": "mcp-manager",
	}); err != nil {
		return "", fmt.Errorf("failed to list deployments: %w", err)
	}

	for _, deployment := range deployments.Items {
		// Check if UID matches
		if string(deployment.UID) == instanceID {
			return strings.TrimPrefix(deployment.Name, "mcp-"), nil
		}
		
		// Check if instance ID matches from annotations
		if annotations := deployment.Spec.Template.ObjectMeta.Annotations; annotations != nil {
			if mcpInstanceID, exists := annotations["agentarea.io/instance-id"]; exists {
				if mcpInstanceID == instanceID {
					return strings.TrimPrefix(deployment.Name, "mcp-"), nil
				}
			}
		}
	}

	return "", fmt.Errorf("instance not found: %s", instanceID)
}

// getDeploymentStatus determines status from deployment conditions
func (k *KubernetesBackend) getDeploymentStatus(deployment *appsv1.Deployment) string {
	if deployment.Status.ReadyReplicas == 0 {
		return "starting"
	}
	
	if deployment.Status.ReadyReplicas < deployment.Status.Replicas {
		return "partial"
	}
	
	if deployment.Status.ReadyReplicas == deployment.Status.Replicas {
		return "running"
	}
	
	// Check conditions for more specific status
	for _, condition := range deployment.Status.Conditions {
		if condition.Type == appsv1.DeploymentProgressing {
			if condition.Status == corev1.ConditionFalse {
				return "error"
			}
		}
	}
	
	return "unknown"
}

// performHTTPHealthCheck performs HTTP health check against the service
func (k *KubernetesBackend) performHTTPHealthCheck(ctx context.Context, instanceName string) (bool, time.Duration) {
	// Use internal service URL for health check
	url := fmt.Sprintf("http://mcp-%s.%s.svc.cluster.local/health", instanceName, k.k8sConfig.Namespace)
	
	start := time.Now()
	client := &http.Client{Timeout: 10 * time.Second}
	
	resp, err := client.Get(url)
	responseTime := time.Since(start)
	
	if err != nil {
		return false, responseTime
	}
	defer resp.Body.Close()
	
	return resp.StatusCode >= 200 && resp.StatusCode < 300, responseTime
}

// Helper function for int32 pointer
func int32Ptr(i int32) *int32 {
	return &i
}